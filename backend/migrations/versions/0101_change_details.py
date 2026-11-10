"""A change's own fields (WP-045a; REQ-CHG-005, -011), number from the coordinator (0099-0103).

Expand only, no data step (no change exists before this build): `work_item_change_details`
(RLS), one row per change keyed (tenant_id, work_item_id), with its type and reason for change
(codes of the tenant's `change_type` and `change_reason` pick lists, which 0102 allows), and
whether it was logged after the fact (`retrospective`, REQ-CHG-004). Like a
release's details it has no version of its own: every edit goes through the change's work item,
whose `version` it bumps (one If-Match for the whole record). Later sessions add their columns
here (risk in WP-045b).

The downgrade drops the table (rule 5h: changes and their fields go with it only on a database
where 0102 was rolled back first, and 0102's downgrade stops while change lists exist).

Revision ID: 0101
Revises: 0100
Created: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0101"
down_revision: str | None = "0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "work_item_change_details"


def upgrade() -> None:
    """The details table."""
    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("change_type", sa.String(40), nullable=True),
        sa.Column("change_reason", sa.String(40), nullable=True),
        # REQ-CHG-004: logged after the fact; reported separately.
        sa.Column("retrospective", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["work_item_id"],
            ["work_items.id"],
            name=op.f(f"fk_{TABLE}_work_item_id_work_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "work_item_id", name=op.f(f"pk_{TABLE}")),
    )
    # Lists and reports filter by type (REQ-CHG-005: types show in lists and the calendar).
    op.create_index(
        "ix_work_item_change_details_tenant_type",
        TABLE,
        ["tenant_id", "change_type"],
        postgresql_where=sa.text("change_type IS NOT NULL"),
    )
    enable_tenant_rls(TABLE)
    enable_actor_audit(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    """Back to before changes' own fields."""
    op.drop_index("ix_work_item_change_details_tenant_type", table_name=TABLE)
    op.drop_table(TABLE)
