"""A request's approval stages (WP-047a S2a; REQ-SR-029..032), 0194.

Expand only, no data step:

- `work_items.approval_stages`: the item's stages snapshotted at submission (configuration
  only: kind and rule codes, IDs, switches and the condition; `{"v": 1, "stages": [...]}`,
  shape-checked by the domain). NULL on every record before S2a, and on requests whose item
  has one stage, which keep running exactly as today (the coordinator's condition 5).
- `work_item_approvals.branch`: the stage's parallel group (REQ-SR-030), NULL when it runs alone.
- `work_item_approvals.skip_reason`: why a stage was skipped (REQ-SR-032: its condition did not
  hold), shown on the record with the condition.
- The state check gains `skipped`; the route reason check gains `no_approver` (a stage whose
  approvers resolve to nobody goes to the approval administrators, recorded: condition 3).

The downgrade stops while any tenant has a skipped row or a `no_approver` route (rule 5h), then
drops the three columns and narrows the checks back.

Revision ID: 0194
Revises: 0191
Created: 2026-11-23
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0194"
# main's head at its queue turn (… 0193 → 0191, WP-047a S1 then CMDB S4a).
down_revision: str | None = "0191"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ITEMS, APPROVALS = "work_items", "work_item_approvals"
STATE_CHECK = "ck_work_item_approvals_state_code"
REASON_CHECK = "ck_work_item_approvals_reason_code"
SKIP_CHECK = "ck_work_item_approvals_skip_reason_code"
ADDED_STATES = ("skipped",)
ADDED_REASONS = ("no_approver",)

# Business tables force RLS: the check runs once per tenant (D-113).
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (
            SELECT 1 FROM {APPROVALS}
            WHERE state = 'skipped' OR route_reason = 'no_approver'
        ) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has staged request approvals', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed names, no input


def _codes_now(check: str) -> list[str]:
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": check},
    )
    return re.findall(r"'([a-z_]+)'::", str(definition))


def _recheck(check: str, expression: str) -> None:
    op.drop_constraint(op.f(check), APPROVALS, type_="check")
    op.create_check_constraint(op.f(check), APPROVALS, expression)


def _listed(codes: Sequence[str]) -> str:
    return ", ".join(f"'{c}'" for c in codes)


def upgrade() -> None:
    """The snapshot, the two approval columns and the widened checks."""
    op.add_column(ITEMS, sa.Column("approval_stages", postgresql.JSONB(), nullable=True))
    op.add_column(APPROVALS, sa.Column("branch", sa.String(40), nullable=True))
    op.add_column(APPROVALS, sa.Column("skip_reason", sa.String(40), nullable=True))
    op.create_check_constraint(
        op.f(SKIP_CHECK), APPROVALS, "skip_reason IS NULL OR skip_reason IN ('condition_not_met')"
    )
    states = _codes_now(STATE_CHECK)
    _recheck(
        STATE_CHECK,
        f"state IN ({_listed([*states, *(c for c in ADDED_STATES if c not in states)])})",
    )
    reasons = _codes_now(REASON_CHECK)
    _recheck(
        REASON_CHECK,
        "route_reason IS NULL OR route_reason IN "
        f"({_listed([*reasons, *(c for c in ADDED_REASONS if c not in reasons)])})",
    )


def downgrade() -> None:
    """Back to before (stops while a staged approval was skipped or routed for nobody)."""
    op.execute(GUARD)
    _recheck(
        REASON_CHECK,
        "route_reason IS NULL OR route_reason IN "
        f"({_listed([c for c in _codes_now(REASON_CHECK) if c not in ADDED_REASONS])})",
    )
    _recheck(
        STATE_CHECK,
        f"state IN ({_listed([c for c in _codes_now(STATE_CHECK) if c not in ADDED_STATES])})",
    )
    op.drop_constraint(op.f(SKIP_CHECK), APPROVALS, type_="check")
    op.drop_column(APPROVALS, "skip_reason")
    op.drop_column(APPROVALS, "branch")
    op.drop_column(ITEMS, "approval_stages")
