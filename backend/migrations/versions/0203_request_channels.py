"""Service request channels (WP-047a S4; REQ-SR-017, -038, -044), 0203.

Expand only, no data step:

- `mailboxes.creates` gains `service_request` (REQ-SR-017: mail to a mapped mailbox makes a
  request of one catalog item); the column widens to 20 characters for the code.
  `mailboxes.catalog_item_id` names that item, set exactly when `creates = 'service_request'`.
  No foreign key: the item is the catalogue's (rule 5e), checked through its public service when
  saved and when mail arrives, as the mailbox's group is.
- `work_items.approval_status` gains `awaiting_answers` (REQ-SR-017 AC2/AC3: a request made
  from mail with required answers missing; its approval starts once they are given).
- `work_item_approvals`: the channel check gains `email_reply` (REQ-SR-038: decided by replying
  to the approval mail); the state check gains `expired` (REQ-SR-044: a workflow or trigger level
  whose timeout passed); `expires_at`, the time it does, for those levels only; `trigger_id`, the
  rule that asked (REQ-SR-044's trigger action), so one rule never asks twice while pending.

The downgrade stops while any tenant has a request mailbox, a reply decision or an expired
approval (rule 5h), then narrows everything back.

Revision ID: 0203
Revises: 0197
Created: 2026-11-25
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0203"
# main's head at its queue turn (… 0198 → 0197, CMDB S5b then WP-047a S3b).
down_revision: str | None = "0197"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAILBOXES, APPROVALS, ITEMS = "mailboxes", "work_item_approvals", "work_items"
ITEM_STATUS_CHECK = "ck_work_items_approval_status_code"
CREATES_CHECK = "ck_mailboxes_creates_code"
ITEM_CHECK = "ck_mailboxes_catalog_item_set"
STATE_CHECK = "ck_work_item_approvals_state_code"
CHANNEL_CHECK = "ck_work_item_approvals_channel_code"
ADDED_STATES = ("expired",)
ADDED_CHANNELS = ("email_reply",)

# Business tables force RLS: the check runs once per tenant (D-113).
GUARD = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {MAILBOXES} WHERE creates = 'service_request')
            OR EXISTS (
                SELECT 1 FROM {APPROVALS} WHERE state = 'expired' OR channel = 'email_reply'
            )
            OR EXISTS (SELECT 1 FROM {ITEMS} WHERE approval_status = 'awaiting_answers')
        THEN
            RAISE EXCEPTION 'downgrade refused: tenant % uses the WP-047a S4 channels', t;
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


def _recheck(table: str, check: str, expression: str) -> None:
    op.drop_constraint(op.f(check), table, type_="check")
    op.create_check_constraint(op.f(check), table, expression)


def _listed(codes: Sequence[str]) -> str:
    return ", ".join(f"'{c}'" for c in codes)


def upgrade() -> None:
    """The mailbox's item, the widened codes and the expiry time."""
    op.alter_column(MAILBOXES, "creates", type_=sa.String(20), existing_type=sa.String(10))
    _recheck(MAILBOXES, CREATES_CHECK, "creates IN ('incident', 'service_request', 'nothing')")
    op.add_column(MAILBOXES, sa.Column("catalog_item_id", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        op.f(ITEM_CHECK),
        MAILBOXES,
        "(catalog_item_id IS NOT NULL) = (creates = 'service_request')",
    )
    states = _codes_now(STATE_CHECK)
    _recheck(
        APPROVALS,
        STATE_CHECK,
        f"state IN ({_listed([*states, *(c for c in ADDED_STATES if c not in states)])})",
    )
    channels = _codes_now(CHANNEL_CHECK)
    _recheck(
        APPROVALS,
        CHANNEL_CHECK,
        "channel IS NULL OR channel IN "
        f"({_listed([*channels, *(c for c in ADDED_CHANNELS if c not in channels)])})",
    )
    op.add_column(APPROVALS, sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(APPROVALS, sa.Column("trigger_id", sa.Uuid(), nullable=True))
    statuses = _codes_now(ITEM_STATUS_CHECK)
    _recheck(
        ITEMS,
        ITEM_STATUS_CHECK,
        "approval_status IS NULL OR approval_status IN "
        f"({_listed([*statuses, *(c for c in ('awaiting_answers',) if c not in statuses)])})",
    )


def downgrade() -> None:
    """Back to before (stops while a request mailbox, reply decision or expiry exists)."""
    op.execute(GUARD)
    _recheck(
        ITEMS,
        ITEM_STATUS_CHECK,
        "approval_status IS NULL OR approval_status IN "
        f"({_listed([c for c in _codes_now(ITEM_STATUS_CHECK) if c != 'awaiting_answers'])})",
    )
    op.drop_column(APPROVALS, "trigger_id")
    op.drop_column(APPROVALS, "expires_at")
    _recheck(
        APPROVALS,
        CHANNEL_CHECK,
        "channel IS NULL OR channel IN "
        f"({_listed([c for c in _codes_now(CHANNEL_CHECK) if c not in ADDED_CHANNELS])})",
    )
    _recheck(
        APPROVALS,
        STATE_CHECK,
        f"state IN ({_listed([c for c in _codes_now(STATE_CHECK) if c not in ADDED_STATES])})",
    )
    op.drop_constraint(op.f(ITEM_CHECK), MAILBOXES, type_="check")
    op.drop_column(MAILBOXES, "catalog_item_id")
    _recheck(MAILBOXES, CREATES_CHECK, "creates IN ('incident', 'nothing')")
    op.alter_column(MAILBOXES, "creates", type_=sa.String(10), existing_type=sa.String(20))
