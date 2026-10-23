"""Housekeeping rights for the relay: expired idempotency keys, old consumer records (WP-012).

The outbox relay already purges published outbox rows (0003). It now also deletes
- idempotency_keys rows whose `expires_at` has passed (follow-up from WP-008), and
- processed_events rows older than 7 days at least (consumer idempotency records, WP-007).

Each through a policy scoped TO supportx_relay alone whose USING clause is the age rule itself,
so the database refuses to let it read or delete anything younger, whatever the code says. The
7-day floor equals the event stream's maximum age: a record a redelivery could still need is never
eligible. Allowlisted in tooling/rls_guard.py.

Revision ID: 0010
Revises: 0009
Created: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

from app.shared.db.rls import RELAY_ROLE

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RULES = {
    "idempotency_keys": "expires_at < now()",
    "processed_events": "created_at < now() - interval '7 days'",
}


def upgrade() -> None:
    for table, rule in RULES.items():
        for command in ("select", "delete"):
            op.execute(
                f"CREATE POLICY {table}_relay_{command} ON {table} FOR {command.upper()} "
                f"TO {RELAY_ROLE} USING ({rule})"
            )
        op.execute(f"GRANT SELECT, DELETE ON {table} TO {RELAY_ROLE}")


def downgrade() -> None:
    for table in RULES:
        op.execute(f"REVOKE ALL ON {table} FROM {RELAY_ROLE}")
        for command in ("select", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_relay_{command} ON {table}")
