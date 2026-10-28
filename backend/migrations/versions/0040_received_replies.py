"""Incoming requester replies are "received" (WP-020f QA BUG-01).

- work_item_conversations.delivery_state takes "received": the requester's own words sent in
  from the portal or by e-mail, which nothing needs to send. They were stored as "not_sent",
  so the console showed them as replies that "reached no one";
- existing such replies (by the requester or the person the record is for) move from
  "not_sent" to "received". The update runs once per tenant with app.tenant_id set: the table
  forces RLS (D-113).

Reversible: the downgrade turns them back to "not_sent" before restoring the constraint.

Revision ID: 0040
Revises: 0039
Created: 2026-10-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_work_item_conversations_delivery_state_code"
TABLE = "work_item_conversations"


RECEIVED = """
DO $$
DECLARE
    t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        UPDATE work_item_conversations c
        SET delivery_state = 'received', delivery_reason = NULL
        FROM work_items w
        WHERE c.tenant_id = t AND w.tenant_id = t AND w.id = c.work_item_id
          AND c.kind = 'reply' AND c.delivery_state = 'not_sent'
          AND c.created_by IN (w.requester_id, w.on_behalf_of_id);
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END
$$;
"""
NOT_SENT = """
DO $$
DECLARE
    t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        UPDATE work_item_conversations
        SET delivery_state = 'not_sent', delivery_reason = 'email_channel_not_configured'
        WHERE tenant_id = t AND delivery_state = 'received';
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END
$$;
"""


def upgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), TABLE, type_="check")
    op.create_check_constraint(
        op.f(CONSTRAINT),
        TABLE,
        "delivery_state IS NULL OR delivery_state IN ('received', 'not_sent', 'queued', 'sent', "
        "'failed')",
    )
    op.execute(RECEIVED)


def downgrade() -> None:
    op.execute(NOT_SENT)
    op.drop_constraint(op.f(CONSTRAINT), TABLE, type_="check")
    op.create_check_constraint(
        op.f(CONSTRAINT),
        TABLE,
        "delivery_state IS NULL OR delivery_state IN ('not_sent', 'queued', 'sent', 'failed')",
    )
