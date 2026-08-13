"""Session artifact store — metadata for agent-published artifacts."""

from __future__ import annotations

import builtins
from abc import ABC, abstractmethod

from omnigent.entities import PagedList, SessionArtifact


class SessionArtifactStore(ABC):
    """
    Abstract base for session-artifact metadata persistence.

    Binary content is managed separately by
    :class:`~omnigent.stores.artifact_store.ArtifactStore`, keyed by the
    artifact id.

    Every operation is session-scoped: an artifact is only ever reachable
    through the session that published it, so reads carry the owning
    session id and verify it.
    """

    def __init__(self, storage_location: str) -> None:
        """
        Initialize the session artifact store.

        :param storage_location: Backend-specific storage URI,
            e.g. ``"sqlite:///omnigent.db"``.
        """
        self.storage_location = storage_location

    @abstractmethod
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
        """
        Record a newly published artifact. Generates a unique id.

        :param session_id: Owning session/conversation id.
        :param filename: Original filename, e.g. ``"final_cut.mp4"``.
        :param content_type: Resolved MIME type, e.g. ``"video/mp4"``.
        :param bytes: Content size in bytes.
        :param title: Optional human-facing title.
        :param description: Optional human-facing description.
        :param preview_artifact_id: Optional sibling artifact that
            previews this one, e.g. a video poster.
        :returns: The newly created :class:`SessionArtifact`.
        """
        ...

    @abstractmethod
    def get(self, artifact_id: str, session_id: str) -> SessionArtifact | None:
        """
        Return the artifact metadata, or ``None`` if not found.

        Only returns the artifact when it belongs to *session_id*.

        :param artifact_id: Unique artifact identifier.
        :param session_id: Owning session/conversation id.
        :returns: The :class:`SessionArtifact`, or ``None``.
        """
        ...

    @abstractmethod
    def list(
        self,
        session_id: str,
        limit: int = 100,
        after: str | None = None,
    ) -> PagedList[SessionArtifact]:
        """
        List a session's artifacts, newest first.

        :param session_id: Owning session whose artifacts to list.
        :param limit: Maximum number of artifacts to return.
        :param after: Cursor artifact id for forward pagination.
        :returns: A :class:`PagedList` of :class:`SessionArtifact`.
        """
        ...

    @abstractmethod
    def delete_all_for_session(self, session_id: str) -> builtins.list[str]:
        """
        Delete all artifact metadata for a session.

        :param session_id: Owning session/conversation id.
        :returns: List of deleted artifact ids, so callers can clean up
            the corresponding blobs.
        """
        ...
