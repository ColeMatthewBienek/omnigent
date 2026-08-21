"""Unit tests for the runner-side ``publish_artifact`` dispatch.

The runner reads the workspace file itself and POSTs it to the server's
session-artifact endpoint, so these cover the two things that can only be
enforced runner-side: workspace containment (the read happens in the
un-sandboxed runner process) and the shape of the multipart request.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from omnigent.runner.tool_dispatch import _execute_artifact_tool

_CONVERSATION_ID = "conv_artifacts"
_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x2a" * 64


def _recording_client(
    captured: list[httpx.Request],
    *,
    status: int = 201,
) -> httpx.AsyncClient:
    """
    Build a server client that records requests and answers with an
    artifact resource.

    :param captured: List each inbound request is appended to.
    :param status: Status the artifacts endpoint answers with.
    :returns: An ``httpx.AsyncClient`` backed by a mock transport.
    """
    counter = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if status >= 400:
            return httpx.Response(status, json={"error": {"message": "nope"}})
        counter["n"] += 1
        return httpx.Response(
            status,
            json={
                "id": f"artifact_{counter['n']}",
                "name": "Final cut",
                "metadata": {
                    "filename": "final_cut.mp4",
                    "content_type": "video/mp4",
                    "bytes": len(_MP4),
                    "render_category": "video",
                },
            },
        )

    return httpx.AsyncClient(
        transport=httpx.MockTransport(_handler),
        base_url="http://ap-server",
    )


@pytest.mark.parametrize(
    "evil_path",
    ["/etc/passwd", "../../../etc/passwd", "../secrets.mp4"],
)
@pytest.mark.asyncio
async def test_publish_rejects_paths_outside_workspace(
    evil_path: str,
    tmp_path: Path,
) -> None:
    """A path escaping the workspace is refused before anything is read.

    :param evil_path: An agent-supplied path resolving outside the root.
    :param tmp_path: Workspace root for the session.
    """
    (tmp_path.parent / "secrets.mp4").write_bytes(b"TOP SECRET")

    captured: list[httpx.Request] = []
    client = _recording_client(captured)
    try:
        result = await _execute_artifact_tool(
            "publish_artifact",
            {"path": evil_path},
            client,
            conversation_id=_CONVERSATION_ID,
            agent_spec=None,
            runner_workspace=tmp_path,
        )
    finally:
        await client.aclose()

    assert result.startswith("Error: publish_artifact failed:"), result
    assert "escapes" in result
    assert captured == [], "an out-of-workspace file was read and POSTed"


@pytest.mark.asyncio
async def test_publish_rejects_symlink_escaping_workspace(tmp_path: Path) -> None:
    """A workspace-local symlink to a host file is refused.

    :param tmp_path: Workspace root for the session.
    """
    secret = tmp_path.parent / "host_secret.mp4"
    secret.write_bytes(b"exfiltrated")
    (tmp_path / "innocent.mp4").symlink_to(secret)

    captured: list[httpx.Request] = []
    client = _recording_client(captured)
    try:
        result = await _execute_artifact_tool(
            "publish_artifact",
            {"path": "innocent.mp4"},
            client,
            conversation_id=_CONVERSATION_ID,
            agent_spec=None,
            runner_workspace=tmp_path,
        )
    finally:
        await client.aclose()

    assert result.startswith("Error: publish_artifact failed:"), result
    assert captured == []


@pytest.mark.asyncio
async def test_publish_posts_the_file_and_its_metadata(tmp_path: Path) -> None:
    """An in-workspace file is POSTed with its bytes, title and description.

    :param tmp_path: Workspace root for the session.
    """
    target = tmp_path / "renders" / "final_cut.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(_MP4)

    captured: list[httpx.Request] = []
    client = _recording_client(captured)
    try:
        result = await _execute_artifact_tool(
            "publish_artifact",
            {
                "path": "renders/final_cut.mp4",
                "title": "Final cut",
                "description": "The approved edit.",
            },
            client,
            conversation_id=_CONVERSATION_ID,
            agent_spec=None,
            runner_workspace=tmp_path,
        )
    finally:
        await client.aclose()

    parsed = json.loads(result)
    assert parsed["artifact_id"] == "artifact_1"
    assert parsed["render_category"] == "video"
    assert len(captured) == 1
    request = captured[0]
    assert request.method == "POST"
    assert request.url.path == f"/v1/sessions/{_CONVERSATION_ID}/resources/artifacts"
    assert _MP4 in request.content
    assert b"Final cut" in request.content
    assert b"The approved edit." in request.content


@pytest.mark.asyncio
async def test_publish_uploads_the_preview_first_and_links_it(tmp_path: Path) -> None:
    """``preview_path`` is published as its own artifact and referenced.

    :param tmp_path: Workspace root for the session.
    """
    (tmp_path / "final_cut.mp4").write_bytes(_MP4)
    (tmp_path / "poster.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    captured: list[httpx.Request] = []
    client = _recording_client(captured)
    try:
        result = await _execute_artifact_tool(
            "publish_artifact",
            {"path": "final_cut.mp4", "preview_path": "poster.png"},
            client,
            conversation_id=_CONVERSATION_ID,
            agent_spec=None,
            runner_workspace=tmp_path,
        )
    finally:
        await client.aclose()

    assert len(captured) == 2, "expected the preview POST then the artifact POST"
    assert b"poster.png" in captured[0].content
    assert b"artifact_1" in captured[1].content
    assert json.loads(result)["preview_artifact_id"] == "artifact_1"


@pytest.mark.asyncio
async def test_publish_surfaces_a_server_rejection(tmp_path: Path) -> None:
    """A server-side 415 reaches the model as an actionable error.

    :param tmp_path: Workspace root for the session.
    """
    (tmp_path / "bundle.mp4").write_bytes(_MP4)

    captured: list[httpx.Request] = []
    client = _recording_client(captured, status=415)
    try:
        result = await _execute_artifact_tool(
            "publish_artifact",
            {"path": "bundle.mp4"},
            client,
            conversation_id=_CONVERSATION_ID,
            agent_spec=None,
            runner_workspace=tmp_path,
        )
    finally:
        await client.aclose()

    assert result.startswith("Error:")
    assert "415" in result


@pytest.mark.asyncio
async def test_publish_requires_a_session(tmp_path: Path) -> None:
    """Artifacts are session-scoped, so a session-less turn cannot publish.

    :param tmp_path: Workspace root for the session.
    """
    captured: list[httpx.Request] = []
    client = _recording_client(captured)
    try:
        result = await _execute_artifact_tool(
            "publish_artifact",
            {"path": "final_cut.mp4"},
            client,
            conversation_id=None,
            agent_spec=None,
            runner_workspace=tmp_path,
        )
    finally:
        await client.aclose()

    assert result.startswith("Error:")
    assert captured == []
