"""The session key ring's key IDs (D-162, ADR-048).

`session_key_ids`: every sign-in session key ID this installation has listed, when it was first
seen and when it left the ring. IDs only, never key material. A platform table: it describes the
installation, not a tenant (the ring is one per installation), so it has no tenant_id. Like the
other platform tables (tenants, tenant_subscriptions) it has RLS enabled and forced, with
policies naming supportx_app alone, and tooling/rls_guard.py lists it with exactly the rights
the app has: SELECT, INSERT and UPDATE, never DELETE. Start-up inserts a new ID with ON CONFLICT
DO NOTHING and retires a missing one with a conditional UPDATE, so of several replicas starting
at once exactly one writes each audit entry.

Expand only, no data step. The downgrade drops the table: it holds no business data, and the
next start-up after an upgrade records the ring again (as first seen at that moment).

Revision ID: 0146
Revises: 0140
Created: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.shared.db.rls import APP_ROLE
from migrations.helpers import grant_app

revision: str = "0146"
down_revision: str | None = "0140"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "session_key_ids"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("key_id", sa.String(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "key_id ~ '^[a-z0-9_-]{1,32}$'", name=op.f("ck_session_key_ids_key_id_format")
        ),
        sa.PrimaryKeyConstraint("key_id", name=op.f("pk_session_key_ids")),
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    # Installation-wide rows: every API process reads and records them, whatever its tenant.
    op.execute(f"CREATE POLICY {TABLE}_app_select ON {TABLE} FOR SELECT TO {APP_ROLE} USING (true)")
    op.execute(
        f"CREATE POLICY {TABLE}_app_insert ON {TABLE} FOR INSERT TO {APP_ROLE} WITH CHECK (true)"
    )
    op.execute(
        f"CREATE POLICY {TABLE}_app_update ON {TABLE} FOR UPDATE TO {APP_ROLE} "
        "USING (true) WITH CHECK (true)"
    )
    grant_app(TABLE, ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    op.drop_table(TABLE)  # drops its policies too
