"""The session key ring's key IDs, its claimed changes and their announcements (D-162, ADR-048).

`session_key_ids`: every sign-in session key ID this installation has listed, when it was first
seen and when it left the ring. IDs only, never key material. A platform table: it describes the
installation, not a tenant (the ring is one per installation), so it has no tenant_id. Like the
other platform tables (tenants, tenant_subscriptions) it has RLS enabled and forced, with
policies naming supportx_app alone, and tooling/rls_guard.py lists it with exactly the rights
the app has: SELECT, INSERT and UPDATE, never DELETE. Start-up inserts a new ID with ON CONFLICT
DO NOTHING and retires a missing one with a conditional UPDATE, so of several replicas starting
at once exactly one writes each audit entry.

`session_key_events`: each claimed change (a key put into use or retired), written in the
claim's transaction, platform table like the above (SELECT, INSERT, UPDATE of `announced_at`).
`session_key_announcements`: tenant-scoped (tenant_id first in its key, RLS with the four tenant
policies, SELECT and INSERT only): which changes are already in the tenant's audit log. The
announcer inserts it in the same transaction as the entry, unique per (tenant, change), so each
tenant gets each entry exactly once.

Expand only, no data step. The downgrade drops the tables: they hold no business data (the
audit entries themselves stay), and the next start-up records the ring again.

Revision ID: 0146
Revises: 0142
Created: 2026-11-12
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from app.shared.db.rls import APP_ROLE
from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0146"
down_revision: str | None = "0142"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "session_key_ids"
EVENTS = "session_key_events"
ANNOUNCEMENTS = "session_key_announcements"
ACTIONS = "('security.session_key_rotated', 'security.session_key_retired')"


def _stamps() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
    ]


def _platform_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    # Installation-wide rows: every API process reads and records them, whatever its tenant.
    op.execute(f"CREATE POLICY {table}_app_select ON {table} FOR SELECT TO {APP_ROLE} USING (true)")
    op.execute(
        f"CREATE POLICY {table}_app_insert ON {table} FOR INSERT TO {APP_ROLE} WITH CHECK (true)"
    )
    op.execute(
        f"CREATE POLICY {table}_app_update ON {table} FOR UPDATE TO {APP_ROLE} "
        "USING (true) WITH CHECK (true)"
    )
    grant_app(table, ("SELECT", "INSERT", "UPDATE"))


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
    _platform_rls(TABLE)

    op.create_table(
        EVENTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("previous_key_id", sa.String(), nullable=True),
        sa.Column("readable_keys", sa.SmallInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.CheckConstraint(f"action IN {ACTIONS}", name=op.f("ck_session_key_events_action_code")),
        # The announcer copies these into every tenant's audit log: the database itself keeps
        # them to key-ID shape and a small count, so a row can never carry free text there
        # (lane A's #418 review).
        sa.CheckConstraint(
            "key_id ~ '^[a-z0-9_-]{1,32}$'", name=op.f("ck_session_key_events_key_id_format")
        ),
        sa.CheckConstraint(
            "previous_key_id IS NULL OR previous_key_id ~ '^[a-z0-9_-]{1,32}$'",
            name=op.f("ck_session_key_events_previous_key_id_format"),
        ),
        sa.CheckConstraint(
            "readable_keys BETWEEN 0 AND 64", name=op.f("ck_session_key_events_readable_keys_range")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_session_key_events")),
    )
    op.create_index(
        "ix_session_key_events_pending",
        EVENTS,
        ["occurred_at"],
        postgresql_where=sa.text("announced_at IS NULL"),
    )
    _platform_rls(EVENTS)

    op.create_table(
        ANNOUNCEMENTS,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("key_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        *_stamps(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_session_key_announcements_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            [f"{EVENTS}.id"],
            name=op.f("fk_session_key_announcements_event_id_session_key_events"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "event_id", name=op.f("pk_session_key_announcements")),
    )
    enable_tenant_rls(ANNOUNCEMENTS)
    # Written once with its audit entry, never changed or removed.
    grant_app(ANNOUNCEMENTS, ("SELECT", "INSERT"))


def downgrade() -> None:
    op.drop_table(ANNOUNCEMENTS)  # drops its policies too
    op.drop_table(EVENTS)
    op.drop_table(TABLE)
