"""The incident board's layout choice (WP-046b S3b; REQ-INC-111), 0182.

Expand only, no data step: two nullable columns on `work_item_list_settings`, a person's own
for one view:

- `layout`: `table` (as today), `cards`, `board` or `calendar`; NULL keeps the table.
- `group_by`: the board's columns: `status`, `priority`, `technician` or `group`; NULL is status.

The downgrade drops both columns: people's choice of layout goes back to the table.

Revision ID: 0182
Revises: 0186
Created: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0182"
down_revision: str | None = "0186"  # main's head at its queue turn (0183 → 0186 → 0182)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "work_item_list_settings"


def upgrade() -> None:
    """Add the two columns and their checks."""
    op.add_column(TABLE, sa.Column("layout", sa.String(10), nullable=True))
    op.create_check_constraint(
        op.f("ck_work_item_list_settings_layout_code"),
        TABLE,
        "layout IS NULL OR layout IN ('table', 'cards', 'board', 'calendar')",
    )
    op.add_column(TABLE, sa.Column("group_by", sa.String(12), nullable=True))
    op.create_check_constraint(
        op.f("ck_work_item_list_settings_group_by_code"),
        TABLE,
        "group_by IS NULL OR group_by IN ('status', 'priority', 'technician', 'group')",
    )


def downgrade() -> None:
    """Drop both columns (their checks go with them)."""
    op.drop_column(TABLE, "group_by")
    op.drop_column(TABLE, "layout")
