"""When a work item was last restored from the trash (Haider, 2026-11-10), number 0128.

Expand only, no data step: `work_items.restored_at` holds the LATEST restore (the history keeps
each one). SLA reports filter on it ("restored from trash"): the clock keeps running while a
record is in the trash, so a restored record may be past due at once.

The downgrade drops the column (expand-only: nothing reads it before this).

Revision ID: 0128
Revises: 0127
Created: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0128"
down_revision: str | None = "0127"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """The column."""
    op.add_column("work_items", sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Drops the column."""
    op.drop_column("work_items", "restored_at")
