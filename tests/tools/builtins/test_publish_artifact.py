"""Unit tests for the publish_artifact built-in tool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from omnigent.entities import SessionArtifact
from omnigent.tools.base import ToolContext
from omnigent.tools.builtins.publish_artifact import PublishArtifactTool


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """
    Create a workspace with publishable and unpublishable files.

    :param tmp_path: Pytest temp directory.
    :returns: The workspace path.
    """
    ws = tmp_path / "workspace"
    (ws / "renders").mkdir(parents=True)
    (ws / "renders" / "final_cut.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x11" * 64)
    (ws / "renders" / "poster.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    (ws / "notes.txt").write_text("not an artifact")
    (tmp_path / "outside.mp4").write_bytes(b"secret")
    return ws


@pytest.fixture()
def tool_ctx(workspace: Path) -> ToolContext:
    """
    Build a ToolContext rooted at the test workspace.

    :param workspace: The workspace directory.
    :returns: A configured ToolContext.
    """
    return ToolContext(
        task_id="task_001",
        agent_id="ag_001",
        workspace=workspace,
        conversation_id="conv_001",
    )


class _FakeSessionArtifactStore:
    """In-memory stand-in for the session artifact store."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self._rows: dict[str, SessionArtifact] = {}

    def create(
        self,
        session_id: str,
        filename: str,
        content_type: str,
        bytes: int,
        title: str | None = None,
        description: str | None = None,
        preview_artifact_id: str | None = None,
    ) -> SessionArtifact:
        """Record the call and return a predictable artifact."""
        artifact_id = f"artifact{len(self.created)}"
        self.created.append(
            {
                "session_id": session_id,
                "filename": filename,
                "content_type": content_type,
                "bytes": bytes,
                "title": title,
                "description": description,
                "preview_artifact_id": preview_artifact_id,
            }
        )
        row = SessionArtifact(
            id=artifact_id,
            session_id=session_id,
            filename=filename,
            content_type=content_type,
            bytes=bytes,
            created_at=1,
            title=title,
            description=description,
            preview_artifact_id=preview_artifact_id,
        )
        self._rows[artifact_id] = row
        return row

    def get(self, artifact_id: str, session_id: str) -> SessionArtifact | None:
        """Return a stored artifact when it belongs to *session_id*."""
        row = self._rows.get(artifact_id)
        if row is None or row.session_id != session_id:
            return None
        return row


class _FakeBlobStore:
    """Stub capturing blob writes."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        """Record the blob."""
        self.blobs[key] = data


@pytest.fixture()
def stores(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, list[Any]]:
    """
    Install fake stores plus an event sink on the runtime globals.

    :param monkeypatch: Pytest monkeypatch fixture.
    :returns: ``(artifact_store, blob_store, published_events)``.
    """
    artifacts = _FakeSessionArtifactStore()
    blobs = _FakeBlobStore()
    events: list[Any] = []

    monkeypatch.setattr("omnigent.runtime.get_session_artifact_store", lambda: artifacts)
    monkeypatch.setattr("omnigent.runtime.get_artifact_store", lambda: blobs)
    monkeypatch.setattr(
        "omnigent.runtime.session_stream.publish",
        lambda session_id, payload: events.append((session_id, payload)),
    )
    return artifacts, blobs, events


def test_publishes_a_video_and_returns_its_metadata(
    tool_ctx: ToolContext,
    stores: tuple[Any, Any, list[Any]],
) -> None:
    """A workspace video is stored with a server-derived render category."""
    artifacts, blobs, _ = stores

    result = json.loads(
        PublishArtifactTool().invoke(
            json.dumps({"path": "renders/final_cut.mp4", "title": "Final cut"}),
            tool_ctx,
        )
    )

    assert result["artifact_id"] == "artifact0"
    assert result["filename"] == "final_cut.mp4"
    assert result["content_type"] == "video/mp4"
    assert result["render_category"] == "video"
    assert result["title"] == "Final cut"
    assert artifacts.created[0]["session_id"] == "conv_001"
    assert blobs.blobs["artifact0"].startswith(b"\x00\x00\x00\x18ftypmp42")


def test_publishing_announces_a_resource_created_event(
    tool_ctx: ToolContext,
    stores: tuple[Any, Any, list[Any]],
) -> None:
    """The UI learns about a new artifact over the session stream."""
    _, _, events = stores

    PublishArtifactTool().invoke(json.dumps({"path": "renders/final_cut.mp4"}), tool_ctx)

    assert len(events) == 1
    session_id, payload = events[0]
    assert session_id == "conv_001"
    assert payload["type"] == "session.resource.created"
    assert payload["resource"]["type"] == "session_artifact"
    assert payload["resource"]["metadata"]["render_category"] == "video"


def test_preview_path_is_published_first_and_linked(
    tool_ctx: ToolContext,
    stores: tuple[Any, Any, list[Any]],
) -> None:
    """A poster is published as its own artifact and referenced by the video."""
    artifacts, _, _ = stores

    result = json.loads(
        PublishArtifactTool().invoke(
            json.dumps(
                {"path": "renders/final_cut.mp4", "preview_path": "renders/poster.png"}
            ),
            tool_ctx,
        )
    )

    assert artifacts.created[0]["filename"] == "poster.png"
    assert artifacts.created[1]["filename"] == "final_cut.mp4"
    assert result["preview_artifact_id"] == "artifact0"


def test_rejects_a_path_escaping_the_workspace(
    tool_ctx: ToolContext,
    stores: tuple[Any, Any, list[Any]],
) -> None:
    """Containment matches upload_file: the read never leaves the workspace."""
    artifacts, _, _ = stores

    result = PublishArtifactTool().invoke(
        json.dumps({"path": "../outside.mp4"}), tool_ctx
    )

    assert result.startswith("Error:")
    assert "escapes workspace" in result
    assert artifacts.created == []


def test_rejects_a_symlink_pointing_outside_the_workspace(
    workspace: Path,
    tool_ctx: ToolContext,
    stores: tuple[Any, Any, list[Any]],
) -> None:
    """A symlink is resolved before the containment check, not after."""
    artifacts, _, _ = stores
    (workspace / "escape.mp4").symlink_to(workspace.parent / "outside.mp4")

    result = PublishArtifactTool().invoke(json.dumps({"path": "escape.mp4"}), tool_ctx)

    assert result.startswith("Error:")
    assert artifacts.created == []


def test_rejects_a_type_off_the_allowlist(
    tool_ctx: ToolContext,
    stores: tuple[Any, Any, list[Any]],
) -> None:
    """Text/code is an attachment, not an artifact."""
    artifacts, _, _ = stores

    result = PublishArtifactTool().invoke(json.dumps({"path": "notes.txt"}), tool_ctx)

    assert result.startswith("Error:")
    assert "text/plain" in result
    assert artifacts.created == []


def test_rejects_content_over_the_size_cap(
    workspace: Path,
    tool_ctx: ToolContext,
    stores: tuple[Any, Any, list[Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An over-cap artifact is refused before anything is stored."""
    artifacts, _, _ = stores
    monkeypatch.setattr(
        "omnigent.runtime.session_artifacts.artifact_upload_limit", lambda _ct: 8
    )

    result = PublishArtifactTool().invoke(
        json.dumps({"path": "renders/final_cut.mp4"}), tool_ctx
    )

    assert result.startswith("Error:")
    assert "exceeds" in result
    assert artifacts.created == []


def test_reports_a_missing_file(
    tool_ctx: ToolContext,
    stores: tuple[Any, Any, list[Any]],
) -> None:
    """A path that isn't a file is reported, not raised."""
    result = PublishArtifactTool().invoke(json.dumps({"path": "nope.mp4"}), tool_ctx)
    assert result.startswith("Error:")
    assert "not found" in result


def test_requires_a_session(
    workspace: Path,
    stores: tuple[Any, Any, list[Any]],
) -> None:
    """Artifacts are session-scoped, so a session-less turn cannot publish."""
    ctx = ToolContext(
        task_id="task_001", agent_id="ag_001", workspace=workspace, conversation_id=None
    )
    result = PublishArtifactTool().invoke(
        json.dumps({"path": "renders/final_cut.mp4"}), ctx
    )
    assert result.startswith("Error:")
