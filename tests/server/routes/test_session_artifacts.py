"""Tests for the session artifact endpoints.

Covers publication (allowlist, size cap, SSE announcement), the listing
route, and the content route's streaming contract: byte ranges, cache
validators, and the inline-vs-attachment decision that keeps agent-authored
HTML out of the server's origin.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from omnigent.errors import OmnigentError
from omnigent.runtime import _globals, set_runner_client, set_runner_router
from omnigent.server.routes.sessions import create_sessions_router
from tests.server.routes.test_session_resources import (
    _ConversationStore,
    _InMemoryArtifactStore,
)

# Sessions defined by the shared _ConversationStore fixture.
_SID = "79b22ebd2309e48fdeb450c65611d51b"
_OTHER_SID = "5d29bee4350489d66feafecfebd94a97"

_MP4 = b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 8


@pytest.fixture
def runner_globals_reset() -> Iterator[None]:
    """Isolate the runner globals so no test leaks a routed runner."""
    prior_client = _globals._runner_client
    prior_router = _globals._runner_router
    set_runner_client(None)
    set_runner_router(None)
    yield
    set_runner_client(prior_client)
    set_runner_router(prior_router)


@pytest.fixture
def conv_store() -> _ConversationStore:
    """Conversation store shared by the app and the assertions."""
    return _ConversationStore()


@pytest.fixture
def session_artifact_store(db_uri: str) -> Any:
    """Real SqlAlchemy session artifact store."""
    from omnigent.stores.session_artifact_store.sqlalchemy_store import (
        SqlAlchemySessionArtifactStore,
    )

    return SqlAlchemySessionArtifactStore(db_uri)


@pytest.fixture
def blob_store() -> _InMemoryArtifactStore:
    """In-memory blob store standing in for the artifact store."""
    return _InMemoryArtifactStore()


def _build_app(
    conv_store: _ConversationStore,
    session_artifact_store: Any,
    blob_store: Any,
    **router_kwargs: Any,
) -> FastAPI:
    """Build a FastAPI app exposing the artifact routes.

    :param conv_store: Conversation store backing session lookups.
    :param session_artifact_store: Artifact metadata store.
    :param blob_store: Artifact blob store.
    :param router_kwargs: Extra kwargs for ``create_sessions_router``.
    :returns: The configured app.
    """
    app = FastAPI()

    @app.exception_handler(OmnigentError)
    async def _handle(request: Request, exc: OmnigentError) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    app.include_router(
        create_sessions_router(
            conv_store,  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]  — stub agent store
            artifact_store=blob_store,
            session_artifact_store=session_artifact_store,
            **router_kwargs,
        ),
        prefix="/v1",
    )
    return app


@pytest.fixture
def artifact_app(
    runner_globals_reset: None,
    conv_store: _ConversationStore,
    session_artifact_store: Any,
    blob_store: _InMemoryArtifactStore,
) -> FastAPI:
    """App with the artifact routes and no auth configured."""
    del runner_globals_reset
    return _build_app(conv_store, session_artifact_store, blob_store)


@pytest.fixture
async def client(artifact_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """httpx client pointed at the artifact-capable app."""
    transport = httpx.ASGITransport(app=artifact_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://server") as c:
        yield c


async def _publish(
    client: httpx.AsyncClient,
    filename: str,
    content: bytes,
    content_type: str,
    session_id: str = _SID,
    **form: str,
) -> httpx.Response:
    """Publish one artifact and return the raw response.

    :param client: Test HTTP client.
    :param filename: Artifact filename.
    :param content: Artifact bytes.
    :param content_type: Declared MIME type.
    :param session_id: Owning session.
    :param form: Extra multipart form fields (title, description, …).
    :returns: The HTTP response.
    """
    return await client.post(
        f"/v1/sessions/{session_id}/resources/artifacts",
        files={"file": (filename, content, content_type)},
        data=form,
    )


# ── Publication ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_and_list_round_trip(client: httpx.AsyncClient) -> None:
    """A published artifact appears in the session's artifact list."""
    resp = await _publish(client, "final_cut.mp4", _MP4, "video/mp4", title="Final cut")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["object"] == "session.resource"
    assert body["type"] == "session_artifact"
    assert body["session_id"] == _SID
    assert body["name"] == "Final cut"
    assert body["metadata"]["render_category"] == "video"
    assert body["metadata"]["content_type"] == "video/mp4"
    assert body["metadata"]["bytes"] == len(_MP4)

    listed = await client.get(f"/v1/sessions/{_SID}/resources/artifacts")
    assert listed.status_code == 200
    assert [a["id"] for a in listed.json()["data"]] == [body["id"]]


@pytest.mark.asyncio
async def test_publish_announces_a_resource_created_event(
    client: httpx.AsyncClient,
    conv_store: _ConversationStore,
) -> None:
    """Publishing emits the ``session.resource.created`` resource event."""
    resp = await _publish(client, "clip.mp4", _MP4, "video/mp4")
    assert resp.status_code == 201

    events = [i for i in conv_store.appended_items if i.type == "resource_event"]
    assert events, "no resource_event persisted"
    data = events[-1].data
    assert data.event_type == "session.resource.created"
    assert data.resource_type == "session_artifact"
    assert data.resource_id == resp.json()["id"]
    assert data.resource["metadata"]["render_category"] == "video"


@pytest.mark.asyncio
async def test_publish_rejects_types_off_the_allowlist(client: httpx.AsyncClient) -> None:
    """A type the artifact surface doesn't render is refused with 415."""
    resp = await _publish(client, "bundle.zip", b"PK\x03\x04", "application/zip")
    assert resp.status_code == 415
    assert "Unsupported artifact type" in resp.text


@pytest.mark.asyncio
async def test_publish_rejects_plain_text(client: httpx.AsyncClient) -> None:
    """Text/code belongs on the attachment surface, not the artifact one."""
    resp = await _publish(client, "notes.txt", b"hello", "text/plain")
    assert resp.status_code == 415


@pytest.mark.asyncio
async def test_publish_enforces_the_configured_size_cap(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An artifact past its per-type cap is rejected with 413."""
    import omnigent.server.server_config as server_config

    monkeypatch.setattr(server_config, "artifact_html_bytes_limit", lambda: 16)
    resp = await _publish(client, "report.html", b"x" * 64, "text/html")
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_publish_links_a_preview_artifact(client: httpx.AsyncClient) -> None:
    """A poster published first can be referenced by the video."""
    poster = await _publish(client, "poster.png", b"\x89PNG\r\n\x1a\n", "image/png")
    poster_id = poster.json()["id"]

    video = await _publish(client, "clip.mp4", _MP4, "video/mp4", preview_artifact_id=poster_id)
    assert video.status_code == 201
    assert video.json()["metadata"]["preview_artifact_id"] == poster_id


@pytest.mark.asyncio
async def test_publish_rejects_a_foreign_preview_artifact(
    client: httpx.AsyncClient,
) -> None:
    """A preview must live in the same session as the artifact it previews."""
    poster = await _publish(
        client, "poster.png", b"\x89PNG\r\n\x1a\n", "image/png", session_id=_OTHER_SID
    )
    resp = await _publish(
        client, "clip.mp4", _MP4, "video/mp4", preview_artifact_id=poster.json()["id"]
    )
    assert resp.status_code == 400


# ── Listing / ownership ────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_never_leaks_another_session(client: httpx.AsyncClient) -> None:
    """Artifacts are visible only through the session that published them."""
    await _publish(client, "mine.mp4", _MP4, "video/mp4")
    listed = await client.get(f"/v1/sessions/{_OTHER_SID}/resources/artifacts")
    assert listed.status_code == 200
    assert listed.json()["data"] == []


@pytest.mark.asyncio
async def test_content_404s_for_the_wrong_session(client: httpx.AsyncClient) -> None:
    """Reading an artifact through a session that doesn't own it 404s."""
    published = await _publish(client, "clip.mp4", _MP4, "video/mp4")
    artifact_id = published.json()["id"]

    resp = await client.get(f"/v1/sessions/{_OTHER_SID}/resources/artifacts/{artifact_id}/content")
    assert resp.status_code == 404


# ── Content route: streaming contract ──────────────────────────


@pytest.mark.asyncio
async def test_content_serves_full_body_with_range_support_advertised(
    client: httpx.AsyncClient,
) -> None:
    """A plain GET returns the bytes and advertises byte-range support."""
    published = await _publish(client, "clip.mp4", _MP4, "video/mp4")
    artifact_id = published.json()["id"]

    resp = await client.get(f"/v1/sessions/{_SID}/resources/artifacts/{artifact_id}/content")
    assert resp.status_code == 200
    assert resp.content == _MP4
    assert resp.headers["content-type"].startswith("video/mp4")
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["etag"] == f'"{artifact_id}"'
    assert "immutable" in resp.headers["cache-control"]
    assert resp.headers["content-disposition"].startswith("inline;")


@pytest.mark.asyncio
async def test_content_honors_a_byte_range(client: httpx.AsyncClient) -> None:
    """A single-range request is answered 206 with the exact slice."""
    published = await _publish(client, "clip.mp4", _MP4, "video/mp4")
    artifact_id = published.json()["id"]

    resp = await client.get(
        f"/v1/sessions/{_SID}/resources/artifacts/{artifact_id}/content",
        headers={"Range": "bytes=10-19"},
    )
    assert resp.status_code == 206
    assert resp.content == _MP4[10:20]
    assert resp.headers["content-range"] == f"bytes 10-19/{len(_MP4)}"
    assert resp.headers["content-length"] == "10"
    assert resp.headers["accept-ranges"] == "bytes"


@pytest.mark.asyncio
async def test_content_honors_an_open_ended_and_suffix_range(
    client: httpx.AsyncClient,
) -> None:
    """``bytes=N-`` and ``bytes=-N`` both resolve against the real size."""
    published = await _publish(client, "clip.mp4", _MP4, "video/mp4")
    artifact_id = published.json()["id"]
    path = f"/v1/sessions/{_SID}/resources/artifacts/{artifact_id}/content"
    size = len(_MP4)

    open_ended = await client.get(path, headers={"Range": "bytes=2040-"})
    assert open_ended.status_code == 206
    assert open_ended.content == _MP4[2040:]
    assert open_ended.headers["content-range"] == f"bytes 2040-{size - 1}/{size}"

    suffix = await client.get(path, headers={"Range": "bytes=-8"})
    assert suffix.status_code == 206
    assert suffix.content == _MP4[-8:]
    assert suffix.headers["content-range"] == f"bytes {size - 8}-{size - 1}/{size}"


@pytest.mark.asyncio
async def test_content_rejects_an_unsatisfiable_range(client: httpx.AsyncClient) -> None:
    """A range starting past the end is answered 416 with the real size."""
    published = await _publish(client, "clip.mp4", _MP4, "video/mp4")
    artifact_id = published.json()["id"]

    resp = await client.get(
        f"/v1/sessions/{_SID}/resources/artifacts/{artifact_id}/content",
        headers={"Range": f"bytes={len(_MP4) + 10}-"},
    )
    assert resp.status_code == 416
    assert resp.headers["content-range"] == f"bytes */{len(_MP4)}"


@pytest.mark.asyncio
async def test_content_ignores_a_multi_range_request(client: httpx.AsyncClient) -> None:
    """Multi-range is not implemented, so the whole body is served instead."""
    published = await _publish(client, "clip.mp4", _MP4, "video/mp4")
    artifact_id = published.json()["id"]

    resp = await client.get(
        f"/v1/sessions/{_SID}/resources/artifacts/{artifact_id}/content",
        headers={"Range": "bytes=0-9,20-29"},
    )
    assert resp.status_code == 200
    assert resp.content == _MP4


@pytest.mark.asyncio
async def test_content_revalidates_with_etag(client: httpx.AsyncClient) -> None:
    """A matching ``If-None-Match`` short-circuits to 304."""
    published = await _publish(client, "clip.mp4", _MP4, "video/mp4")
    artifact_id = published.json()["id"]

    resp = await client.get(
        f"/v1/sessions/{_SID}/resources/artifacts/{artifact_id}/content",
        headers={"If-None-Match": f'"{artifact_id}"'},
    )
    assert resp.status_code == 304
    assert resp.headers["accept-ranges"] == "bytes"


# ── Content route: disposition policy ──────────────────────────


@pytest.mark.asyncio
async def test_audio_and_image_are_served_inline(client: httpx.AsyncClient) -> None:
    """Passive media categories may render in place."""
    for filename, content_type in (("mix.mp3", "audio/mpeg"), ("chart.png", "image/png")):
        published = await _publish(client, filename, b"bytes-here", content_type)
        artifact_id = published.json()["id"]
        resp = await client.get(f"/v1/sessions/{_SID}/resources/artifacts/{artifact_id}/content")
        assert resp.headers["content-disposition"].startswith("inline;"), filename


@pytest.mark.asyncio
async def test_html_is_always_served_as_an_attachment(client: httpx.AsyncClient) -> None:
    """Agent-authored HTML must never execute in the server's origin."""
    published = await _publish(client, "report.html", b"<script>alert(1)</script>", "text/html")
    artifact_id = published.json()["id"]

    resp = await client.get(f"/v1/sessions/{_SID}/resources/artifacts/{artifact_id}/content")
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("attachment;")
    assert resp.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_unrecognised_type_is_served_as_an_attachment(
    client: httpx.AsyncClient,
    session_artifact_store: Any,
    blob_store: _InMemoryArtifactStore,
) -> None:
    """A ``download``-category row (not publishable via the API) stays a download."""
    artifact = session_artifact_store.create(
        session_id=_SID,
        filename="mystery.bin",
        content_type="application/octet-stream",
        bytes=4,
    )
    blob_store.put(artifact.id, b"\x00\x01\x02\x03")

    resp = await client.get(f"/v1/sessions/{_SID}/resources/artifacts/{artifact.id}/content")
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("attachment;")


# ── Authorization boundary ─────────────────────────────────────


@pytest.fixture
def authed_client_factory(
    runner_globals_reset: None,
    conv_store: _ConversationStore,
    session_artifact_store: Any,
    blob_store: _InMemoryArtifactStore,
    db_uri: str,
) -> Any:
    """Factory building a client whose identity comes from a request header."""
    del runner_globals_reset
    from omnigent.stores.permission_store.sqlalchemy_store import (
        SqlAlchemyPermissionStore,
    )

    permission_store = SqlAlchemyPermissionStore(db_uri)

    class _HeaderAuthProvider:
        """Reads the caller's identity from ``X-Test-User``."""

        def get_user_id(self, request: Request) -> str | None:
            """:returns: The header value, or ``None`` when absent."""
            return request.headers.get("x-test-user")

        def is_local_single_user(self) -> bool:
            """:returns: ``False`` — these tests are multi-user."""
            return False

    app = _build_app(
        conv_store,
        session_artifact_store,
        blob_store,
        auth_provider=_HeaderAuthProvider(),  # type: ignore[arg-type]
        permission_store=permission_store,
    )

    def _make(user_id: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://server",
            headers={"X-Test-User": user_id},
        )

    _make.permission_store = permission_store  # type: ignore[attr-defined]
    return _make


@pytest.mark.asyncio
async def test_list_requires_read_access(authed_client_factory: Any) -> None:
    """A caller with no grant cannot see that the session has artifacts."""
    authed_client_factory.permission_store.grant("owner@example.com", _SID, 4)

    async with authed_client_factory("stranger@example.com") as stranger:
        resp = await stranger.get(f"/v1/sessions/{_SID}/resources/artifacts")
        assert resp.status_code == 404

    async with authed_client_factory("owner@example.com") as owner:
        resp = await owner.get(f"/v1/sessions/{_SID}/resources/artifacts")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_publish_requires_edit_access(authed_client_factory: Any) -> None:
    """A read-only grantee may read artifacts but may not publish one."""
    authed_client_factory.permission_store.grant("owner@example.com", _SID, 4)
    authed_client_factory.permission_store.grant("reader@example.com", _SID, 1)

    async with authed_client_factory("owner@example.com") as owner:
        published = await _publish(owner, "clip.mp4", _MP4, "video/mp4")
        assert published.status_code == 201
        artifact_id = published.json()["id"]

    async with authed_client_factory("reader@example.com") as reader:
        denied = await _publish(reader, "sneaky.mp4", _MP4, "video/mp4")
        assert denied.status_code == 403

        allowed = await reader.get(
            f"/v1/sessions/{_SID}/resources/artifacts/{artifact_id}/content"
        )
        assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_content_requires_read_access(authed_client_factory: Any) -> None:
    """Artifact bytes are not readable without a grant on the session."""
    authed_client_factory.permission_store.grant("owner@example.com", _SID, 4)
    async with authed_client_factory("owner@example.com") as owner:
        published = await _publish(owner, "clip.mp4", _MP4, "video/mp4")
        artifact_id = published.json()["id"]

    async with authed_client_factory("stranger@example.com") as stranger:
        resp = await stranger.get(f"/v1/sessions/{_SID}/resources/artifacts/{artifact_id}/content")
        assert resp.status_code == 404
