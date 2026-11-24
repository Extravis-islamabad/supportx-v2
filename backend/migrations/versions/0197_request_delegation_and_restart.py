"""Approval delegation and restarting approval for requests (WP-047a S3b), 0197.

REQ-SR-035, REQ-SR-041. Expand only, no data step:

- `approval_delegations` (RLS): an approver's delegate for a date range. Never oneself, ending
  after it starts, at most 90 days long (the coordinator's condition 1), with an optional reason
  and an early end (`ended_at`).
- `work_item_approvals.on_behalf_of_id`: the approver a delegation routed the approval away from
  (they may still decide it; a decision by the delegate reads "A on behalf of B").
- `work_item_approvals.round` (1): the approval round; a restart opens the next and only the
  latest counts (041), earlier decisions staying in history.

The downgrade stops while any tenant has a delegation, a delegated approval or a second round
(rule 5h), then drops the table and the columns.

Revision ID: 0197
Revises: 0196
Created: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0197"
down_revision: str | None = "0196"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPROVALS, TABLE = "work_item_approvals", "approval_delegations"
ROUND_CHECK = "ck_work_item_approvals_round_positive"
ROUND_INDEX = "ix_wia_tenant_item_round"
ON_BEHALF_FK = "fk_wia_on_behalf_of"

# Business tables force RLS: the check runs once per tenant (D-113).
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TABLE})
           OR EXISTS (SELECT 1 FROM {APPROVALS} WHERE on_behalf_of_id IS NOT NULL OR round > 1)
        THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has S3b request approvals', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed names, no input


def _users_fk(column: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column], ["users.tenant_id", "users.id"], name=op.f(f"fk_{TABLE}_{name}")
    )


def upgrade() -> None:
    """The delegations table and the approval's delegation and round columns."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("delegator_id", sa.Uuid(), nullable=False),
        sa.Column("delegate_id", sa.Uuid(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        _users_fk("delegator_id", "delegator"),
        _users_fk("delegate_id", "delegate"),
        sa.CheckConstraint("delegator_id <> delegate_id", name=op.f(f"ck_{TABLE}_not_oneself")),
        sa.CheckConstraint("ends_at > starts_at", name=op.f(f"ck_{TABLE}_ends_after_start")),
        sa.CheckConstraint(
            "ends_at - starts_at <= interval '90 days'", name=op.f(f"ck_{TABLE}_length_capped")
        ),
        sa.CheckConstraint(
            "reason IS NULL OR char_length(reason) <= 500", name=op.f(f"ck_{TABLE}_reason_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(
        "ix_approval_delegations_tenant_delegator",
        TABLE,
        ["tenant_id", "delegator_id", "starts_at"],
    )
    op.create_index("ix_approval_delegations_tenant_delegate", TABLE, ["tenant_id", "delegate_id"])
    enable_tenant_rls(TABLE)
    enable_actor_audit(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))
    op.add_column(APPROVALS, sa.Column("on_behalf_of_id", sa.Uuid(), nullable=True))
    op.add_column(APPROVALS, sa.Column("round", sa.Integer(), server_default="1", nullable=False))
    op.create_foreign_key(
        ON_BEHALF_FK,
        APPROVALS,
        "users",
        ["tenant_id", "on_behalf_of_id"],
        ["tenant_id", "id"],
    )
    op.create_check_constraint(op.f(ROUND_CHECK), APPROVALS, "round >= 1")
    op.create_index(ROUND_INDEX, APPROVALS, ["tenant_id", "work_item_id", "round"])


def downgrade() -> None:
    """Back to before (stops while a delegation, a delegated approval or a second round exists)."""
    op.execute(GUARD)
    op.drop_index(ROUND_INDEX, table_name=APPROVALS)
    op.drop_constraint(op.f(ROUND_CHECK), APPROVALS, type_="check")
    op.drop_constraint(ON_BEHALF_FK, APPROVALS, type_="foreignkey")
    op.drop_column(APPROVALS, "round")
    op.drop_column(APPROVALS, "on_behalf_of_id")
    op.drop_index("ix_approval_delegations_tenant_delegate", table_name=TABLE)
    op.drop_index("ix_approval_delegations_tenant_delegator", table_name=TABLE)
    op.drop_table(TABLE)
