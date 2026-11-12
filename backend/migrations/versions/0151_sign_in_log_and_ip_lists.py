"""The sign-in log and the IP allow-lists (identity_access; WP-057 S1a: REQ-AUD-015, REQ-SEC-034).

Expand only, no data step:
- `sign_in_events`: one row per sign-in event of a tenant (append-only: UPDATE of ip and device
  only, DELETE only past 90 days): success, a refusal with its reason,
  sign-out, lock-out, a failed MFA code. Written by the BFF for what it decides, and imported from
  Keycloak's events for what Keycloak decides (a wrong password), only into the tenant whose own
  address or organization the attempt carried (lane B's review: never every tenant a person is
  in). `ip` and `device` are personal data: the GDPR erasure job nulls them (UPDATE), and rows go
  after 90 days (DELETE, as connector_runs' retention). Never the name typed for an unknown
  person (`user_id` is set only when Keycloak resolved one). Tenant-scoped, RLS forced.
- `sign_in_import_cursor`: where the Keycloak events import got to. Installation-wide (Keycloak's
  events are the realm's), one row per realm.
- `identity_settings`: an IP allow-list per app (console, portal, API) as `cidr[]`, at most 50
  entries each; empty = no restriction.

The downgrade refuses while any tenant has a sign-in event or an allow-list entry, per tenant
with app.tenant_id set (rule 5h).

Revision ID: 0151
Revises: 0150
Created: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.shared.db.rls import APP_ROLE, CURRENT_TENANT_SQL
from migrations.helpers import enable_tenant_rls, grant_app

revision: str = "0151"
down_revision: str | None = "0150"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENTS = "sign_in_events"
CURSOR = "sign_in_import_cursor"
SETTINGS = "identity_settings"
LISTS = ("console_ip_allow", "portal_ip_allow", "api_ip_allow")
MAX_ENTRIES = 50
OUTCOMES = ("success", "failed", "signed_out", "locked", "mfa_failed")
METHODS = ("password", "single_sign_on", "directory", "mobile", "api_key", "unknown")
APPS = ("console", "portal", "api", "mobile")
SOURCES = ("bff", "keycloak")
RETENTION_DAYS = 90  # service/sign_in_log.RETENTION


def _in(column: str, codes: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(c) for c in codes)})"


def upgrade() -> None:
    """Adds the sign-in log, its import cursor and the allow-list columns."""
    op.create_table(
        EVENTS,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(60), nullable=True),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("app", sa.String(10), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("device", sa.String(120), nullable=True),
        sa.Column("identity_provider", sa.String(80), nullable=True),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("keycloak_event_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(_in("outcome", OUTCOMES), name=op.f(f"ck_{EVENTS}_outcome_code")),
        sa.CheckConstraint(_in("method", METHODS), name=op.f(f"ck_{EVENTS}_method_code")),
        sa.CheckConstraint(_in("app", APPS), name=op.f(f"ck_{EVENTS}_app_code")),
        sa.CheckConstraint(_in("source", SOURCES), name=op.f(f"ck_{EVENTS}_source_code")),
        sa.CheckConstraint(
            "(source = 'keycloak') = (keycloak_event_id IS NOT NULL)",
            name=op.f(f"ck_{EVENTS}_keycloak_event_id"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{EVENTS}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_sign_in_events_user",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f(f"pk_{EVENTS}")),
    )
    op.create_index("ix_sign_in_events_recent", EVENTS, ["tenant_id", sa.text("occurred_at DESC")])
    op.create_index(
        "ix_sign_in_events_person",
        EVENTS,
        ["tenant_id", "user_id", sa.text("occurred_at DESC")],
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    # The import is idempotent: one row per Keycloak event and tenant.
    op.create_index(
        "uq_sign_in_events_keycloak",
        EVENTS,
        ["tenant_id", "keycloak_event_id"],
        unique=True,
        postgresql_where=sa.text("keycloak_event_id IS NOT NULL"),
    )
    enable_tenant_rls(EVENTS)
    # Append-only (lane B's #455 review): UPDATE only of ip and device (the GDPR erasure nulls
    # them), never of what happened; DELETE only of rows past the retention (the restrictive
    # policy below), so no code path can rewrite or trim the log early. Never TRUNCATE.
    grant_app(EVENTS, ("SELECT", "INSERT", "DELETE"))
    op.execute(f"GRANT UPDATE (ip, device) ON {EVENTS} TO {APP_ROLE}")
    # Restrictive: ANDed with the tenant policy; it repeats the tenant match, as every policy
    # here does (tooling/rls_guard.py).
    op.execute(
        f"CREATE POLICY {EVENTS}_retention_only ON {EVENTS} AS RESTRICTIVE FOR DELETE "
        f"TO {APP_ROLE} USING (tenant_id = {CURRENT_TENANT_SQL} "
        f"AND occurred_at < now() - interval '{RETENTION_DAYS} days')"
    )

    op.create_table(
        CURSOR,
        sa.Column("realm", sa.String(60), nullable=False),
        sa.Column("last_time_ms", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("realm", name=op.f(f"pk_{CURSOR}")),
    )
    op.execute(f"ALTER TABLE {CURSOR} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {CURSOR} FORCE ROW LEVEL SECURITY")
    # Installation-wide: the realm's events belong to no one tenant.
    op.execute(
        f"CREATE POLICY {CURSOR}_app_select ON {CURSOR} FOR SELECT TO {APP_ROLE} USING (true)"
    )
    op.execute(
        f"CREATE POLICY {CURSOR}_app_insert ON {CURSOR} FOR INSERT TO {APP_ROLE} WITH CHECK (true)"
    )
    op.execute(
        f"CREATE POLICY {CURSOR}_app_update ON {CURSOR} FOR UPDATE TO {APP_ROLE} "
        "USING (true) WITH CHECK (true)"
    )
    grant_app(CURSOR, ("SELECT", "INSERT", "UPDATE"))

    for column in LISTS:
        op.add_column(
            SETTINGS,
            sa.Column(
                column,
                postgresql.ARRAY(postgresql.CIDR()),
                server_default=sa.text("'{}'::cidr[]"),
                nullable=False,
            ),
        )
        op.create_check_constraint(
            op.f(f"ck_{SETTINGS}_{column}_size"),
            SETTINGS,
            f"cardinality({column}) <= {MAX_ENTRIES}",
        )


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {EVENTS}) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has sign-in events (rule 5h)', t;
        END IF;
        IF EXISTS (
            SELECT 1 FROM {SETTINGS}
            WHERE cardinality(console_ip_allow) + cardinality(portal_ip_allow)
                + cardinality(api_ip_allow) > 0
        ) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has an IP allow-list (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def downgrade() -> None:
    """Drops the log, the cursor and the lists only while nothing uses them; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY)
    for column in LISTS:
        op.drop_constraint(op.f(f"ck_{SETTINGS}_{column}_size"), SETTINGS, type_="check")
        op.drop_column(SETTINGS, column)
    op.drop_table(CURSOR)
    op.drop_table(EVENTS)
