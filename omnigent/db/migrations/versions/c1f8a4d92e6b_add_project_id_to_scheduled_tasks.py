"""add project_id to scheduled_tasks

Revision ID: c1f8a4d92e6b
Revises: e6f7a8b9c0d1
Create Date: 2026-08-03 00:00:00.000000

Rebased to descend from e6f7a8b9c0d1 (compress projects.config): this
migration originally reused the revision id d5e6f7a8b9c0, which collided
with upstream's independently-created d5e6f7a8b9c0 (rename
projects.owner_user_id). Renumbered to a fresh id during the upstream
merge; no behavior change.

Lets a scheduled task file its fired sessions into a first-class project.
Adds a nullable ``project_id`` (Uuid16) to ``scheduled_tasks``, mirroring
``c2d3e4f5a6b7_add_project_id_to_conversation_metadata``. ``NULL`` means fired
sessions are left unfiled (today's behavior).

Additive. No foreign-key constraint (schema Rule R032): the project
relationship is enforced by the application (create/update reject a
nonexistent project; the fire path soft-fails a vanished one), not the
database.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from omnigent.db.db_models import Uuid16

revision: str = "c1f8a4d92e6b"
down_revision: str | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable ``project_id`` column."""
    with op.batch_alter_table("scheduled_tasks") as batch_op:
        batch_op.add_column(sa.Column("project_id", Uuid16(), nullable=True))


def downgrade() -> None:
    """Drop the ``project_id`` column."""
    with op.batch_alter_table("scheduled_tasks") as batch_op:
        batch_op.drop_column("project_id")
