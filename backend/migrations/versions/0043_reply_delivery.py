"""Reply delivery states and the e-mail carrying each reply (WP-024 session 3).

Expand only (D-113: a merged migration is never edited):
- work_item_conversations: `delivery_updated_at`; the delivery state gains `waiting` and
  `retrying`, the reason gains the sender's codes. `not_sent` and its reason stay allowed
  (and labelled) until a later contract step, so old rows never show a raw code. `received`
  (lane A's 0040) is listed too, so the check holds before and after it.
- Data, per tenant under FORCE RLS: replies "not sent: email channel not configured" (the
  placeholder before WP-024) now wait for mail like new ones. The downgrade moves them back.
- notification_deliveries: `entry_id` (the reply an e-mail carries) and lookups by entry and by
  mail ID (a send attempt's end finds its rows).

Revision ID: 0043
Revises: 0042 (lane A's 0040 and lane C's 0041 come first at merge)
Created: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATES_BEFORE = ("not_sent", "queued", "sent", "failed", "received")
STATES = (*STATES_BEFORE, "waiting", "retrying")
REASONS_BEFORE = ("email_channel_not_configured",)
REASONS = (
    *REASONS_BEFORE,
    "mail_not_configured",
    "not_sent_in_time",
    "no_address",
    "mail_refused",
    "not_notified",
    "recipient_refused",
    "recipient_deferred",
    "message_refused",
    "authentication_failed",
    "server_unavailable",
    "server_busy",
    "gave_up",
)


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IS NULL OR {column} IN ({', '.join(repr(v) for v in values)})"


_LOOP_HEAD = """
DO $$
DECLARE
    t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
"""
_LOOP_TAIL = """
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END
$$;
"""


def _per_tenant(statement: str) -> str:
    """One fixed statement (written in this file) for each tenant, under FORCE RLS."""
    return _LOOP_HEAD + statement + _LOOP_TAIL


TO_WAITING = _per_tenant(
    "UPDATE work_item_conversations SET delivery_state = 'waiting',"
    " delivery_reason = 'mail_not_configured'"
    " WHERE tenant_id = t AND delivery_state = 'not_sent'"
    " AND delivery_reason = 'email_channel_not_configured';"
)
BACK_TO_NOT_SENT = _per_tenant(
    "UPDATE work_item_conversations SET delivery_state = 'not_sent',"
    " delivery_reason = 'email_channel_not_configured'"
    " WHERE tenant_id = t AND delivery_state IN ('waiting', 'retrying');"
)


def _checks(states: Sequence[str], reasons: Sequence[str]) -> None:
    table = "work_item_conversations"
    for name in ("delivery_state_code", "delivery_reason_code"):
        op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(
        op.f(f"ck_{table}_delivery_state_code"), table, _in("delivery_state", states)
    )
    op.create_check_constraint(
        op.f(f"ck_{table}_delivery_reason_code"), table, _in("delivery_reason", reasons)
    )


def upgrade() -> None:
    op.add_column(
        "work_item_conversations",
        sa.Column("delivery_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    _checks(STATES, REASONS)
    op.execute(TO_WAITING)
    op.add_column("notification_deliveries", sa.Column("entry_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_notification_deliveries_tenant_entry",
        "notification_deliveries",
        ["tenant_id", "entry_id"],
        postgresql_where=sa.text("entry_id IS NOT NULL"),
    )
    op.create_index(
        "ix_notification_deliveries_tenant_mail",
        "notification_deliveries",
        ["tenant_id", "mail_id"],
        postgresql_where=sa.text("mail_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_notification_deliveries_tenant_mail", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_tenant_entry", table_name="notification_deliveries")
    op.drop_column("notification_deliveries", "entry_id")
    # Replies the engine moved since (queued, sent, failed with a new reason) keep their state;
    # only the new states and reasons go back to what the old checks allow.
    op.execute(BACK_TO_NOT_SENT)
    op.execute(
        _per_tenant(
            "UPDATE work_item_conversations SET delivery_reason = NULL"
            " WHERE tenant_id = t AND delivery_reason IS NOT NULL"
            " AND delivery_reason <> 'email_channel_not_configured';"
        )
    )
    _checks(STATES_BEFORE, REASONS_BEFORE)
    op.drop_column("work_item_conversations", "delivery_updated_at")
