"""Who may edit a stage and who may move a record out of it (WP-058a s3; REQ-REL-019; ADR-041).

Type-generic (releases now, changes later), number from the coordinator. Expand only, no data
step: `work_item_stages.access` (JSONB object, NULL by default) holds, for `edit` and
`move_out`, the groups, permissions and record roles allowed. NULL or an empty rule means anyone
who may edit the record (no lock-out). The service checks it on write; the policy layer applies
it (architecture.md §11.2).

Revision ID: 0094
Revises: 0093
Created: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0094"
down_revision: str | None = "0093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """The access column."""
    op.add_column("work_item_stages", sa.Column("access", postgresql.JSONB(), nullable=True))
    op.create_check_constraint(
        op.f("ck_work_item_stages_access_object"),
        "work_item_stages",
        "access IS NULL OR jsonb_typeof(access) = 'object'",
    )


def downgrade() -> None:
    """Drop it again."""
    op.drop_constraint(op.f("ck_work_item_stages_access_object"), "work_item_stages", type_="check")
    op.drop_column("work_item_stages", "access")
