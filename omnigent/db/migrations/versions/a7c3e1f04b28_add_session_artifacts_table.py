"""add session_artifacts table

Revision ID: a7c3e1f04b28
Revises: za2b3c4d5e6f
Create Date: 2026-08-13 00:00:00.000000

Adds the ``session_artifacts`` table: metadata for agent-published,
session-scoped artifacts (a rendered video, an audio mix, a chart, a
report). The bytes live in the existing artifact store keyed by the row's
``id``; only the metadata is relational.

The table is brand-new and is created at the current schema state, so it
carries the tenant-partition ``workspace_id`` column as the leading
primary-key member (matching every other table after ``r1a2b3c4d5e6``).
There are no foreign-key constraints (schema Rule R032 — see
``p1a2b3c4d5e6``): the ``session_id`` and self-referential
``preview_artifact_id`` relationships are enforced by the application.

There is no ``render_category`` column. How an artifact renders is
derived from ``content_type`` on read, so a stored category can never
disagree with the bytes' declared type.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from omnigent.db.db_models import Uuid16

revision: str = "a7c3e1f04b28"
down_revision: str | None = "za2b3c4d5e6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the ``session_artifacts`` table and its listing index."""
    op.create_table(
        "session_artifacts",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False, server_default="0"),
        # UUID PK + session/preview refs stored as 16 raw bytes (Uuid16 →
        # BINARY(16) on MySQL, BLOB/BYTEA elsewhere).
        sa.Column("id", Uuid16(), nullable=False),
        sa.Column("session_id", Uuid16(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(256), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("description", sa.String(2048), nullable=True),
        # Sibling artifact that previews this one (e.g. a video poster).
        sa.Column("preview_artifact_id", Uuid16(), nullable=True),
        sa.PrimaryKeyConstraint("workspace_id", "id"),
    )
    op.create_index(
        "ix_session_artifacts_session_id_created_at",
        "session_artifacts",
        ["workspace_id", "session_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the ``session_artifacts`` table."""
    op.drop_index(
        "ix_session_artifacts_session_id_created_at",
        table_name="session_artifacts",
    )
    op.drop_table("session_artifacts")
