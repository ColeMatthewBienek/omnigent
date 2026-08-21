"""SQLAlchemy-backed session artifact store."""

from __future__ import annotations

import builtins

from sqlalchemy import and_, desc, or_, select

from omnigent.db.db_models import SqlSessionArtifact, current_workspace_id, normalize_uuid
from omnigent.db.utils import (
    generate_session_artifact_id,
    get_or_create_engine,
    make_named_managed_session_maker,
    now_epoch,
)
from omnigent.entities import PagedList, SessionArtifact
from omnigent.stores.session_artifact_store import SessionArtifactStore


def _to_entity(row: SqlSessionArtifact) -> SessionArtifact:
    """
    Convert a :class:`SqlSessionArtifact` ORM row to the entity.

    :param row: The SQLAlchemy ORM row to convert.
    :returns: A :class:`SessionArtifact` dataclass instance.
    """
    return SessionArtifact(
        id=row.id,
        session_id=row.session_id,
        filename=row.filename,
        content_type=row.content_type,
        bytes=row.bytes,
        created_at=row.created_at,
        title=row.title,
        description=row.description,
        preview_artifact_id=row.preview_artifact_id,
    )


class SqlAlchemySessionArtifactStore(SessionArtifactStore):
    """
    SQLAlchemy-backed implementation of :class:`SessionArtifactStore`.

    Persists artifact metadata in a relational database via SQLAlchemy ORM.
    """

    def __init__(self, storage_location: str) -> None:
        """
        Initialize the SQLAlchemy session artifact store.

        :param storage_location: SQLAlchemy database URI,
            e.g. ``"sqlite:///omnigent.db"``.
        """
        super().__init__(storage_location)
        self._engine = get_or_create_engine(storage_location)
        self._session = make_named_managed_session_maker(
            self._engine,
            query_name_prefix="omnigent.session_artifact_store",
        )

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
        Record a newly published artifact in the database.

        :param session_id: Owning session/conversation id.
        :param filename: Original filename.
        :param content_type: Resolved MIME type.
        :param bytes: Content size in bytes.
        :param title: Optional human-facing title.
        :param description: Optional human-facing description.
        :param preview_artifact_id: Optional previewing sibling artifact.
        :returns: The newly created :class:`SessionArtifact`.
        """
        row = SqlSessionArtifact(
            id=generate_session_artifact_id(),
            session_id=session_id,
            created_at=now_epoch(),
            filename=filename,
            content_type=content_type,
            bytes=bytes,
            title=title,
            description=description,
            preview_artifact_id=preview_artifact_id,
        )
        with self._session("insert_session_artifact") as session:
            session.add(row)
            return _to_entity(row)

    def get(self, artifact_id: str, session_id: str) -> SessionArtifact | None:
        """
        Fetch artifact metadata by id, scoped to its owning session.

        :param artifact_id: Unique artifact identifier.
        :param session_id: Owning session/conversation id.
        :returns: The :class:`SessionArtifact`, or ``None``.
        """
        with self._session("select_session_artifact_by_id") as session:
            row = session.get(SqlSessionArtifact, (current_workspace_id(), artifact_id))
            if row is None:
                return None
            if row.session_id != normalize_uuid(session_id):
                return None
            return _to_entity(row)

    def list(
        self,
        session_id: str,
        limit: int = 100,
        after: str | None = None,
    ) -> PagedList[SessionArtifact]:
        """
        List a session's artifacts, newest first.

        Scoped to ``session_id``, so the query is served by
        ``ix_session_artifacts_session_id_created_at``.

        :param session_id: Owning session whose artifacts to list.
        :param limit: Maximum number of artifacts to return.
        :param after: Cursor artifact id for forward pagination.
        :returns: A :class:`PagedList` of :class:`SessionArtifact`.
        """
        with self._session("list_session_artifacts") as session:
            stmt = select(SqlSessionArtifact).where(
                SqlSessionArtifact.workspace_id == current_workspace_id(),
                SqlSessionArtifact.session_id == session_id,
            )
            if after:
                sub = (
                    select(SqlSessionArtifact.created_at)
                    .where(
                        SqlSessionArtifact.workspace_id == current_workspace_id(),
                        SqlSessionArtifact.id == after,
                    )
                    .scalar_subquery()
                )
                stmt = stmt.where(
                    or_(
                        SqlSessionArtifact.created_at < sub,
                        and_(
                            SqlSessionArtifact.created_at == sub,
                            SqlSessionArtifact.id < after,
                        ),
                    )
                )
            stmt = stmt.order_by(
                desc(SqlSessionArtifact.created_at),
                desc(SqlSessionArtifact.id),
            ).limit(limit + 1)
            rows = list(session.execute(stmt).scalars().all())
            has_more = len(rows) > limit
            if has_more:
                rows = rows[:limit]
            entities = [_to_entity(r) for r in rows]
            return PagedList(
                data=entities,
                first_id=entities[0].id if entities else None,
                last_id=entities[-1].id if entities else None,
                has_more=has_more,
            )

    def delete_all_for_session(self, session_id: str) -> builtins.list[str]:
        """
        Delete all artifact metadata for a session.

        :param session_id: Owning session/conversation id.
        :returns: List of deleted artifact ids for blob cleanup.
        """
        with self._session("delete_session_artifacts") as session:
            stmt = select(SqlSessionArtifact).where(
                SqlSessionArtifact.workspace_id == current_workspace_id(),
                SqlSessionArtifact.session_id == session_id,
            )
            rows = list(session.execute(stmt).scalars().all())
            ids = [row.id for row in rows]
            for row in rows:
                session.delete(row)
            return ids
