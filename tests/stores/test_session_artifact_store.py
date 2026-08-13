"""Tests for SqlAlchemySessionArtifactStore."""

from __future__ import annotations

import pytest

from omnigent.stores.session_artifact_store.sqlalchemy_store import (
    SqlAlchemySessionArtifactStore,
)

_SID = "94c349190e241f85a984b3df8f129696"
_OTHER_SID = "1f2e3d4c5b6a79880011223344556677"


@pytest.fixture()
def artifact_store(db_uri: str) -> SqlAlchemySessionArtifactStore:
    """
    :returns: A SqlAlchemySessionArtifactStore backed by the test database.
    """
    return SqlAlchemySessionArtifactStore(db_uri)


def test_create_and_get(artifact_store: SqlAlchemySessionArtifactStore) -> None:
    """A created artifact round-trips with its metadata intact."""
    created = artifact_store.create(
        session_id=_SID,
        filename="final_cut.mp4",
        content_type="video/mp4",
        bytes=4096,
        title="Final cut",
        description="The approved edit.",
    )
    assert len(created.id) == 32
    assert created.render_category == "video"

    fetched = artifact_store.get(created.id, session_id=_SID)
    assert fetched is not None
    assert fetched.filename == "final_cut.mp4"
    assert fetched.content_type == "video/mp4"
    assert fetched.bytes == 4096
    assert fetched.title == "Final cut"
    assert fetched.description == "The approved edit."
    assert fetched.preview_artifact_id is None


def test_get_scoped_to_owning_session(artifact_store: SqlAlchemySessionArtifactStore) -> None:
    """A read from the wrong session cannot see another session's artifact."""
    created = artifact_store.create(
        session_id=_SID,
        filename="clip.mp4",
        content_type="video/mp4",
        bytes=1,
    )
    assert artifact_store.get(created.id, session_id=_OTHER_SID) is None


def test_list_is_newest_first(
    artifact_store: SqlAlchemySessionArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Listing returns the session's artifacts newest-first.

    ``created_at`` has one-second resolution, so the timestamps are forced
    apart here — two artifacts published inside the same second fall back to
    the id tie-break, which is arbitrary by design.
    """
    clock = iter([1000, 2000])
    monkeypatch.setattr(
        "omnigent.stores.session_artifact_store.sqlalchemy_store.now_epoch",
        lambda: next(clock),
    )
    first = artifact_store.create(
        session_id=_SID, filename="a.mp4", content_type="video/mp4", bytes=1
    )
    second = artifact_store.create(
        session_id=_SID, filename="b.mp4", content_type="video/mp4", bytes=1
    )
    ids = [a.id for a in artifact_store.list(session_id=_SID).data]
    assert ids[:2] == [second.id, first.id]


def test_list_excludes_other_sessions(artifact_store: SqlAlchemySessionArtifactStore) -> None:
    """Listing never leaks another session's artifacts."""
    artifact_store.create(
        session_id=_OTHER_SID, filename="other.mp4", content_type="video/mp4", bytes=1
    )
    mine = artifact_store.create(
        session_id=_SID, filename="mine.mp4", content_type="video/mp4", bytes=1
    )
    assert [a.id for a in artifact_store.list(session_id=_SID).data] == [mine.id]


def test_preview_reference_round_trips(artifact_store: SqlAlchemySessionArtifactStore) -> None:
    """A poster artifact can be referenced by the video it previews."""
    poster = artifact_store.create(
        session_id=_SID, filename="poster.png", content_type="image/png", bytes=10
    )
    video = artifact_store.create(
        session_id=_SID,
        filename="clip.mp4",
        content_type="video/mp4",
        bytes=20,
        preview_artifact_id=poster.id,
    )
    fetched = artifact_store.get(video.id, session_id=_SID)
    assert fetched is not None
    assert fetched.preview_artifact_id == poster.id


def test_delete_all_for_session(artifact_store: SqlAlchemySessionArtifactStore) -> None:
    """Session teardown returns the ids so blob cleanup can follow."""
    a = artifact_store.create(session_id=_SID, filename="a.mp4", content_type="video/mp4", bytes=1)
    b = artifact_store.create(session_id=_SID, filename="b.mp4", content_type="video/mp4", bytes=1)
    deleted = artifact_store.delete_all_for_session(_SID)
    assert set(deleted) == {a.id, b.id}
    assert artifact_store.list(session_id=_SID).data == []
