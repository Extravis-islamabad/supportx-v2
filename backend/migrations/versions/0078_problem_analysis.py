"""A problem's analysis (WP-044b s1; REQ-PRB-030, D-140 Q7).

- work_items.root_cause and symptoms: sanitised rich text, problems only (the service refuses
  them on other types). The root cause is read only by holders of problems.view_root_cause and
  is not part of the search text (SEARCH_VECTOR names subject, description and custom text only).

Expand only, no data step. The downgrade drops the two columns.

Revision ID: 0078
Revises: 0089
Created: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0078"
down_revision: str | None = "0089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """The two columns."""
    op.add_column("work_items", sa.Column("root_cause", sa.Text(), nullable=True))
    op.add_column("work_items", sa.Column("symptoms", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop them."""
    op.drop_column("work_items", "symptoms")
    op.drop_column("work_items", "root_cause")
