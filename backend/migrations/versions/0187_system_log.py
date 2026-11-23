"""The system log (WP-057 S5b, REQ-AUD-016): what the platform did on its own, and what failed.

- system_log_entries: one row per event a module records (a mailbox check that failed, a sync,
  an import, a retention run). Tenant-scoped with RLS. **Append-only by grants** (AC2): the app
  may INSERT and SELECT only, so no route, job or bug can change or remove an entry.
- system_log_purge(): the one way rows leave. A migrator-owned SECURITY DEFINER function (the
  #476 helper) that deletes the current tenant's rows older than its retention. It computes the
  cut-off itself from audit_settings (90 days without a row, never under 30): the app passes no
  date, so it can never empty the log early (as audit_purge_access does).
- audit_settings.system_log_retention_days: the tenant's period (30 to 730 days, 90 by default).

Not partitioned (unlike audit_entries): entries are small and a tenant's purge is one indexed
range delete; partitions can follow if volume needs them (an expand migration).

Revision ID: 0187
Revises: 0190
Created: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import (
    create_definer_function,
    drop_definer_function,
    enable_actor_audit,
    enable_tenant_rls,
    grant_app,
)

revision: str = "0187"
down_revision: str | None = "0190"  # main's head at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "system_log_entries"
SEVERITIES = "('info', 'warning', 'error')"
PURGE = "system_log_purge()"

# Deletes the current tenant's entries past its retention. RLS (FORCE) binds the owner too, so it
# reaches only the tenant in app.tenant_id.
PURGE_BODY = """
DECLARE
    t uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
    days integer;
    removed integer;
BEGIN
    IF t IS NULL THEN
        RAISE EXCEPTION 'system_log_purge needs app.tenant_id';
    END IF;
    SELECT s.system_log_retention_days INTO days FROM public.audit_settings s WHERE s.tenant_id = t;
    days := GREATEST(COALESCE(days, 90), 30);
    DELETE FROM public.system_log_entries
     WHERE tenant_id = t AND occurred_at < now() - make_interval(days => days);
    GET DIAGNOSTICS removed = ROW_COUNT;
    RETURN removed;
END
"""


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("module", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=96), nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("object_type", sa.String(length=64), nullable=True),
        sa.Column("object_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"severity IN {SEVERITIES}", name=op.f(f"ck_{TABLE}_severity_code")),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_.]*$'", name=op.f(f"ck_{TABLE}_code_shape")),
        sa.CheckConstraint("module ~ '^[a-z][a-z0-9_]*$'", name=op.f(f"ck_{TABLE}_module_shape")),
        sa.CheckConstraint(
            "jsonb_typeof(params) = 'object'", name=op.f(f"ck_{TABLE}_params_object")
        ),
        sa.CheckConstraint(
            "(object_type IS NULL) = (object_id IS NULL)", name=op.f(f"ck_{TABLE}_object_pair")
        ),
    )
    op.create_index(
        op.f("ix_system_log_entries_tenant_time"), TABLE, ["tenant_id", "occurred_at", "id"]
    )
    op.create_index(
        op.f("ix_system_log_entries_tenant_severity_time"),
        TABLE,
        ["tenant_id", "severity", "occurred_at"],
    )
    op.create_index(
        op.f("ix_system_log_entries_tenant_object"),
        TABLE,
        ["tenant_id", "object_type", "object_id"],
        postgresql_where=sa.text("object_id IS NOT NULL"),
    )
    enable_tenant_rls(TABLE)
    enable_actor_audit(TABLE)
    grant_app(TABLE, ("SELECT", "INSERT"))  # append-only (AC2): no UPDATE, no DELETE
    create_definer_function(
        "system_log_purge",
        "",
        "integer",
        PURGE_BODY,
        language="plpgsql",
        volatility="VOLATILE",
    )
    op.add_column(
        "audit_settings",
        sa.Column("system_log_retention_days", sa.Integer(), nullable=False, server_default="90"),
    )
    op.create_check_constraint(
        op.f("ck_audit_settings_system_log_retention_range"),
        "audit_settings",
        "system_log_retention_days BETWEEN 30 AND 730",
    )


_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {TABLE}) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has system log entries (append-only)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - a fixed table name, no input


def downgrade() -> None:
    """Drops the log only while no tenant has an entry: the table is append-only (lane B, #567).

    Dropping it with rows would be a way round the grants (SELECT and INSERT only), so the
    downgrade refuses as 0180's does, counting per tenant with `app.tenant_id` set (forced RLS).
    """
    op.execute(_REFUSE_IF_ANY)
    op.drop_constraint(
        op.f("ck_audit_settings_system_log_retention_range"), "audit_settings", type_="check"
    )
    op.drop_column("audit_settings", "system_log_retention_days")
    drop_definer_function(PURGE)
    op.drop_table(TABLE)
