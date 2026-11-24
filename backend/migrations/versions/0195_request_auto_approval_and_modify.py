"""Automatic approval and adjusting a running approval (WP-047a S2b; REQ-SR-033, -042), 0195.

Expand only, no data step:

- `work_item_approvals.auto_reason`: why a stage's approval was given automatically (REQ-SR-033):
  `approved_earlier` (the person approved an earlier stage of the same request) or
  `rule_matched` (one of the stage's rules held). Set exactly when `channel = 'automatic'`.
- `work_item_approvals.auto_ref`: the earlier stage's number, or the matched rule's number in the
  request's stage snapshot (1-based), so the record can say which.
- The channel check gains `automatic`; the state check gains `replaced` (REQ-SR-042 AC1: a
  technician replaced the approver, whose approval is withdrawn); the purpose check gains
  `ad_hoc` (REQ-SR-042: named people asked on a service request as on an incident, apart from
  the item's own approval, so its decision never moves the request).
- `work_item_type_settings.auto_approve_earlier`: the tenant's "approved earlier" switch, off by
  default; an item's own setting overrides it (the coordinator's Q1).

The downgrade stops while any tenant has an automatic or a replaced approval (rule 5h), then
drops the columns and narrows the checks back.

Revision ID: 0195
Revises: 0192
Created: 2026-11-24
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0195"
# main's head at its queue turn (… 0194 → 0192, WP-047a S2a then CMDB S4b).
down_revision: str | None = "0192"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPROVALS, SETTINGS = "work_item_approvals", "work_item_type_settings"
STATE_CHECK = "ck_work_item_approvals_state_code"
CHANNEL_CHECK = "ck_work_item_approvals_channel_code"
AUTO_CHECK = "ck_work_item_approvals_auto_reason_code"
AUTO_SET_CHECK = "ck_work_item_approvals_auto_reason_set"
AUTO_REF_CHECK = "ck_work_item_approvals_auto_ref_positive"
PURPOSE_CHECK = "ck_work_item_approvals_purpose_code"
ADDED_STATES = ("replaced",)
ADDED_CHANNELS = ("automatic",)
ADDED_PURPOSES = ("ad_hoc",)

# Business tables force RLS: the check runs once per tenant (D-113).
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (
            SELECT 1 FROM {APPROVALS}
            WHERE state = 'replaced' OR channel = 'automatic' OR purpose = 'ad_hoc'
        ) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has S2b request approvals', t;
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
    """The two approval columns, their checks, the widened codes and the tenant switch."""
    op.add_column(APPROVALS, sa.Column("auto_reason", sa.String(40), nullable=True))
    op.add_column(APPROVALS, sa.Column("auto_ref", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f(AUTO_CHECK),
        APPROVALS,
        "auto_reason IS NULL OR auto_reason IN ('approved_earlier', 'rule_matched')",
    )
    op.create_check_constraint(
        op.f(AUTO_SET_CHECK),
        APPROVALS,
        "(auto_reason IS NOT NULL) = (channel IS NOT DISTINCT FROM 'automatic')",
    )
    op.create_check_constraint(op.f(AUTO_REF_CHECK), APPROVALS, "auto_ref IS NULL OR auto_ref >= 1")
    states = _codes_now(STATE_CHECK)
    _recheck(
        STATE_CHECK,
        f"state IN ({_listed([*states, *(c for c in ADDED_STATES if c not in states)])})",
    )
    channels = _codes_now(CHANNEL_CHECK)
    _recheck(
        CHANNEL_CHECK,
        "channel IS NULL OR channel IN "
        f"({_listed([*channels, *(c for c in ADDED_CHANNELS if c not in channels)])})",
    )
    purposes = _codes_now(PURPOSE_CHECK)
    _recheck(
        PURPOSE_CHECK,
        f"purpose IN ({_listed([*purposes, *(c for c in ADDED_PURPOSES if c not in purposes)])})",
    )
    op.add_column(
        SETTINGS,
        sa.Column("auto_approve_earlier", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    """Back to before (stops while an approval was automatic or replaced)."""
    op.execute(GUARD)
    op.drop_column(SETTINGS, "auto_approve_earlier")
    _recheck(
        PURPOSE_CHECK,
        f"purpose IN ({_listed([c for c in _codes_now(PURPOSE_CHECK) if c not in ADDED_PURPOSES])})",
    )
    _recheck(
        CHANNEL_CHECK,
        "channel IS NULL OR channel IN "
        f"({_listed([c for c in _codes_now(CHANNEL_CHECK) if c not in ADDED_CHANNELS])})",
    )
    _recheck(
        STATE_CHECK,
        f"state IN ({_listed([c for c in _codes_now(STATE_CHECK) if c not in ADDED_STATES])})",
    )
    op.drop_constraint(op.f(AUTO_REF_CHECK), APPROVALS, type_="check")
    op.drop_constraint(op.f(AUTO_SET_CHECK), APPROVALS, type_="check")
    op.drop_constraint(op.f(AUTO_CHECK), APPROVALS, type_="check")
    op.drop_column(APPROVALS, "auto_ref")
    op.drop_column(APPROVALS, "auto_reason")
