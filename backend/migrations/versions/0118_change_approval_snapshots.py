"""Re-approval snapshots (WP-045b S4; REQ-CHG-053), number 0118 from the coordinator.

Expand only, no data step:
- `change_approval_snapshots` (RLS): what a change's watched values were when one of its stages
  was approved (the implementation window, the effective risk, the plan sections' versions), one
  row per approval round, insert-only for the application role. A later save compares against
  the stage's latest row.
- `work_item_type_settings.reapproval` (JSONB, NULL: the shipped policy): per watched value,
  restart, notify or ignore, and the window's tolerance in minutes.
- `work_item_approvals.advisory` (false): an optional board member's approval, recorded and shown
  but never counted under any rule (Haider, 2026-11-10).
- `work_item_change_details`: `resume_stage` and `resume_status`, where a change sent back for
  approval was (the emergency override returns it there), and `pir_required`, set by that
  override: the change closes only through its review (D-144).

The downgrade drops both while no snapshot exists and no tenant set a policy; otherwise it stops
and keeps the data (rule 5h).

Revision ID: 0118
Revises: 0117
Created: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0118"
down_revision: str | None = "0117"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE, DETAILS = "change_approval_snapshots", "work_item_change_details"
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TABLE}) OR EXISTS (
            SELECT 1 FROM work_item_type_settings WHERE reapproval IS NOT NULL
        ) OR EXISTS (
            SELECT 1 FROM work_item_approvals WHERE advisory
        ) OR EXISTS (
            SELECT 1 FROM work_item_change_details
            WHERE pir_required OR resume_stage IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has re-approval data (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - a fixed table name, no input


def upgrade() -> None:
    """The snapshots and the policy setting."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("record_stage", sa.String(40), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
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
            ["tenant_id", "work_item_id"],
            ["work_items.tenant_id", "work_items.id"],
            name=op.f(f"fk_{TABLE}_work_item"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(
        f"ix_{TABLE}_tenant_item_stage",
        TABLE,
        ["tenant_id", "work_item_id", "record_stage", "created_at"],
    )
    enable_tenant_rls(TABLE)
    enable_actor_audit(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT"))
    op.add_column(
        "work_item_type_settings", sa.Column("reapproval", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "work_item_approvals",
        sa.Column("advisory", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(DETAILS, sa.Column("resume_stage", sa.String(40), nullable=True))
    op.add_column(DETAILS, sa.Column("resume_status", sa.String(40), nullable=True))
    op.add_column(
        DETAILS, sa.Column("pir_required", sa.Boolean(), server_default="false", nullable=False)
    )


def downgrade() -> None:
    """Back to before re-approval (stops while there are snapshots or a policy)."""
    op.execute(GUARD)
    for column in ("pir_required", "resume_status", "resume_stage"):
        op.drop_column(DETAILS, column)
    op.drop_column("work_item_approvals", "advisory")
    op.drop_column("work_item_type_settings", "reapproval")
    op.drop_index(f"ix_{TABLE}_tenant_item_stage", table_name=TABLE)
    op.drop_table(TABLE)
