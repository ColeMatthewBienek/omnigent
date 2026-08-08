"""Drop delegated approval authority from session permissions.

Reverts the ``session_permissions.can_approve`` column added in
c4d5e6f7a8b9, which shipped delegated approval authority (feat #3446).
The feature is being withdrawn, but c4d5e6f7a8b9 is kept intact so
already-migrated databases resolve their history — this forward
migration drops the column rather than deleting the original revision.

Additive and reversible: ``downgrade`` re-adds the column with its
original default-off definition.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"
# FORK RE-CHAIN: upstream revises e6f7a8b9c0d1; re-parented onto the local
# scheduled-task chain head (e2b9c5f18a3d) so the fork's migration history
# stays single-headed and live DBs stamped at e2b9c5f18a3d apply this on the
# next upgrade. Operations touch only session_permissions - order-independent
# of the scheduled_tasks chain.
down_revision: str | None = "e2b9c5f18a3d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove the delegated approval capability column."""
    with op.batch_alter_table("session_permissions") as batch_op:
        batch_op.drop_column("can_approve")


def downgrade() -> None:
    """Restore the owner-controlled approval capability column."""
    with op.batch_alter_table("session_permissions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "can_approve",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
