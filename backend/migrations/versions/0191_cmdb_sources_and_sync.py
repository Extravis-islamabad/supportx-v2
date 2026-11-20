"""CMDB attribute sources and sync rules from assets (WP-053 S4a; REQ-CMDB-015, 016), 0191.

Expand only, no data step:
- `cmdb_cis.sources`: each attribute's source and time, `{attribute: {source, at}}`, set by
  the path that wrote the value. Existing CIs start empty: until a path stamps an attribute,
  the service treats its value as set by the CI's own origin (`source`), so a sync never
  overwrites a hand-entered value from before this migration.
- `cmdb_settings.source_precedence`: which source wins, `{order, overrides}`; empty means the
  defaults (hand, import, asset sync, discovery, MonetX, integration).
- `cmdb_sync_rules`: which assets become CIs of which type, and the field map (CI attribute →
  asset field). Soft delete; a live rule's name is unique.
- `cmdb_sync_runs`: each run's trigger, status, counts and a capped list of item outcomes (IDs
  and codes only). Written by the worker.

Both tables are tenant-scoped with RLS forced, through migrations/helpers.py only; every index
starts with tenant_id. The downgrade refuses while any tenant has a rule, a run, a stamped
attribute or an order of its own (rule 5h), per tenant with app.tenant_id set.

Revision ID: 0191
Revises: 0185 (main's head now; re-pointed at its queue turn)
Created: 2026-11-21
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0191"
down_revision: str | None = "0185"  # main's head now; re-pointed at its queue turn
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RULES = "cmdb_sync_rules"
RUNS = "cmdb_sync_runs"
CIS = "cmdb_cis"
SETTINGS = "cmdb_settings"
SOURCES = ("assets",)
TRIGGERS = ("schedule", "manual", "asset_changed")
STATUSES = ("queued", "running", "succeeded", "failed")


def _codes(column: str, codes: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


def _entity_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
    ]


def _audit_columns() -> list[sa.Column[Any]]:
    return [
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
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def _to(column: str, target: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column], [f"{target}.tenant_id", f"{target}.id"], name=name
    )


def _count(name: str) -> sa.Column[Any]:
    return sa.Column(name, sa.BigInteger(), server_default="0", nullable=False)


def upgrade() -> None:
    """The two columns and the two tables."""
    op.add_column(
        CIS, sa.Column("sources", postgresql.JSONB(), server_default="{}", nullable=False)
    )
    op.add_column(
        SETTINGS,
        sa.Column("source_precedence", postgresql.JSONB(), server_default="{}", nullable=False),
    )
    op.create_table(
        RULES,
        *_entity_columns(),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("source_kind", sa.String(length=20), server_default="assets", nullable=False),
        sa.Column("filter", postgresql.JSONB(), nullable=True),
        sa.Column("target_type_id", sa.Uuid(), nullable=False),
        sa.Column("target_state_id", sa.Uuid(), nullable=True),
        sa.Column("field_map", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        *_audit_columns(),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 200", name=op.f(f"ck_{RULES}_name_length")
        ),
        sa.CheckConstraint(
            _codes("source_kind", SOURCES), name=op.f(f"ck_{RULES}_source_kind_code")
        ),
        _tenant_fk(RULES),
        _to("target_type_id", "cmdb_ci_types", "fk_cmdb_sync_rules_type"),
        _to("target_state_id", "cmdb_ci_states", "fk_cmdb_sync_rules_state"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{RULES}")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_cmdb_sync_rules_tenant_id_id"),
    )
    op.create_index(
        "uq_cmdb_sync_rules_name",
        RULES,
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_cmdb_sync_rules_tenant_updated", RULES, ["tenant_id", "updated_at", "id"])
    op.create_table(
        RUNS,
        *_entity_columns(),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("asset_ids", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        _count("created_count"),
        _count("updated_count"),
        _count("kept_count"),
        _count("unchanged_count"),
        _count("failed_count"),
        sa.Column("outcomes", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("failure", sa.String(length=60), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(_codes("trigger", TRIGGERS), name=op.f(f"ck_{RUNS}_trigger_code")),
        sa.CheckConstraint(_codes("status", STATUSES), name=op.f(f"ck_{RUNS}_status_code")),
        _tenant_fk(RUNS),
        _to("rule_id", RULES, "fk_cmdb_sync_runs_rule"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{RUNS}")),
    )
    op.create_index("ix_cmdb_sync_runs_tenant_rule", RUNS, ["tenant_id", "rule_id", "created_at"])
    op.create_index(
        "ix_cmdb_sync_runs_tenant_open",
        RUNS,
        ["tenant_id", "created_at"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    for table in (RULES, RUNS):
        enable_tenant_rls(table)
        grant_app(table, ("SELECT", "INSERT", "UPDATE"))  # soft delete only
        enable_actor_audit(table)


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE); a fixed statement.
_REFUSE_IF_ANY = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM cmdb_sync_rules) OR EXISTS (SELECT 1 FROM cmdb_sync_runs)
            OR EXISTS (SELECT 1 FROM cmdb_cis WHERE sources <> '{}'::jsonb)
            OR EXISTS (SELECT 1 FROM cmdb_settings WHERE source_precedence <> '{}'::jsonb)
        THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has CMDB sources or sync rules (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drops the tables and columns only while no tenant has anything in them."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_table(RUNS)  # its indexes and policies go with it
    op.drop_table(RULES)
    op.drop_column(SETTINGS, "source_precedence")
    op.drop_column(CIS, "sources")
