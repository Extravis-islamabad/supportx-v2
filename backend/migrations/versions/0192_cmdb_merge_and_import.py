"""CMDB merge, aliases and import (WP-053 S4b; REQ-CMDB-017, 018; the coordinator's 0192).

- cmdb_ci_aliases: one CI merged into another. The merged CI goes to the trash; this row is its
  alias: its ID (and its display ID, for search) find the survivor, for a reader who may see the
  survivor only. `mapping` is the field-by-field choice (codes only; the values are in each CI's
  history), `moved` the counts of what moved. A restore of the merged CI ends the alias
  (`restored_at`) and moves nothing back.
- cmdb_imports: one CSV or Excel file of CIs or relationships, read in the background (the
  assets' import pattern): a dry run checks every row in savepoints it rolls back; the file is
  kept until the real run has read it. Results keep counts and per-row problems (row, column,
  code), never values.

Tenant first, RLS forced (migrations/helpers.py only), soft delete, actor audit. The downgrade
refuses while any tenant has an alias or an import (rule 5h), per tenant with app.tenant_id set.

Revision ID: 0192
Revises: 0190 (re-pointed at its queue turn, after S4a's 0191)
Created: 2026-11-23
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0192"
down_revision: str | None = "0190"  # main's head now; re-pointed at its queue turn (after 0191)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALIASES = "cmdb_ci_aliases"
IMPORTS = "cmdb_imports"
KINDS = ("cis", "relationships")
MODES = ("add", "update", "add_update")
MATCHES = ("display_id", "name")
STATUSES = ("queued", "running", "checked", "done", "failed")


def _codes(column: str, codes: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{c}'" for c in codes) + ")"


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


def _count(name: str) -> sa.Column[Any]:
    return sa.Column(name, sa.Integer(), server_default="0", nullable=False)


def upgrade() -> None:
    """The aliases and the imports."""
    op.create_table(
        ALIASES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("alias_id", sa.Uuid(), nullable=False),
        sa.Column("ci_id", sa.Uuid(), nullable=False),
        sa.Column("alias_display_id", sa.String(length=20), nullable=False),
        sa.Column("mapping", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("moved", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restored_by", sa.Uuid(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint("alias_id <> ci_id", name=op.f(f"ck_{ALIASES}_not_self")),
        _tenant_fk(ALIASES),
        sa.ForeignKeyConstraint(
            ["tenant_id", "alias_id"],
            ["cmdb_cis.tenant_id", "cmdb_cis.id"],
            name="fk_cmdb_ci_aliases_alias",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ci_id"],
            ["cmdb_cis.tenant_id", "cmdb_cis.id"],
            name="fk_cmdb_ci_aliases_ci",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ALIASES}")),
    )
    op.create_index(
        "uq_cmdb_ci_aliases_live",
        ALIASES,
        ["tenant_id", "alias_id"],
        unique=True,
        postgresql_where=sa.text("restored_at IS NULL AND deleted_at IS NULL"),
    )
    op.create_index("ix_cmdb_ci_aliases_tenant_ci", ALIASES, ["tenant_id", "ci_id"])
    op.create_index(
        "ix_cmdb_ci_aliases_tenant_display",
        ALIASES,
        ["tenant_id", sa.text("lower(alias_display_id)")],
    )
    enable_tenant_rls(ALIASES)
    grant_app(ALIASES, ("SELECT", "INSERT", "UPDATE"))  # a restore ends an alias; never deleted
    enable_actor_audit(ALIASES)

    op.create_table(
        IMPORTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("match_on", sa.String(length=20), nullable=False),
        sa.Column("type_id", sa.Uuid(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_format", sa.String(length=10), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        _count("total"),
        _count("processed"),
        _count("created_count"),
        _count("updated_count"),
        _count("unchanged_count"),
        _count("failed_count"),
        sa.Column("problems", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("failure", sa.String(length=50), nullable=True),
        sa.Column("failure_detail", sa.String(length=100), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(_codes("kind", KINDS), name=op.f(f"ck_{IMPORTS}_kind_code")),
        sa.CheckConstraint(_codes("mode", MODES), name=op.f(f"ck_{IMPORTS}_mode_code")),
        sa.CheckConstraint(_codes("match_on", MATCHES), name=op.f(f"ck_{IMPORTS}_match_code")),
        sa.CheckConstraint(_codes("status", STATUSES), name=op.f(f"ck_{IMPORTS}_status_code")),
        sa.CheckConstraint(
            "kind <> 'cis' OR type_id IS NOT NULL", name=op.f(f"ck_{IMPORTS}_cis_have_a_type")
        ),
        _tenant_fk(IMPORTS),
        sa.ForeignKeyConstraint(
            ["tenant_id", "type_id"],
            ["cmdb_ci_types.tenant_id", "cmdb_ci_types.id"],
            name="fk_cmdb_imports_type",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{IMPORTS}")),
    )
    op.create_index("ix_cmdb_imports_requested", IMPORTS, ["tenant_id", "created_by", "created_at"])
    op.create_index(
        "ix_cmdb_imports_pending",
        IMPORTS,
        ["tenant_id", "created_at"],
        postgresql_where=sa.text("status IN ('queued', 'running') AND deleted_at IS NULL"),
    )
    enable_tenant_rls(IMPORTS)
    grant_app(IMPORTS, ("SELECT", "INSERT", "UPDATE"))  # soft delete only
    enable_actor_audit(IMPORTS)


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE); fixed statements.
_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM {ALIASES}) OR EXISTS (SELECT 1 FROM {IMPORTS}) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has CI merges or imports (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def downgrade() -> None:
    """Drops both tables only while no tenant has a row (rule 5h)."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_table(IMPORTS)
    op.drop_table(ALIASES)
