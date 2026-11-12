"""Asset bulk jobs, merges and imports (WP-049b S4b).

REQ-AST-051 (bulk actions), 052 (merge duplicates), 053 (import). Expand only, no data step:
- `asset_bulk_jobs`: a bulk edit, move, assign or delete of up to 1,000 frozen assets, with a
  result per asset (done, or skipped with the reason code), run by the consumers worker.
- `asset_merges`: one asset merged into another: the field-by-field choice (codes only), and
  the merged asset's tag, serial and barcode as an alias that finds the survivor. One live
  merge per merged asset; a restore of the merged asset ends its alias.
- `asset_imports`: a CSV or Excel file of assets, consumables or vendors: mode, match, dry
  run, progress, per-row problems; the file is kept only until the real run has read it.

All tenant-scoped with RLS forced, actor audit, and no DELETE grant (soft delete only). The
downgrade refuses while any tenant has a row in a new table, per tenant with app.tenant_id set
(rule 5h).

Revision ID: 0145
Revises: 0140
Created: 2026-11-11
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

if TYPE_CHECKING:
    from datetime import datetime

revision: str = "0145"
# Re-pointed onto main's head at the lane's queue turn (the coordinator's order).
down_revision: str | None = "0140"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = ("asset_imports", "asset_merges", "asset_bulk_jobs")
# The same lists as app/modules/assets/domain/batch.py.
BULK_ACTIONS = ("edit", "move", "assign", "delete")
BULK_STATUSES = ("queued", "running", "done", "failed")
BULK_MAX = 1000
IMPORT_KINDS = ("assets", "consumables", "vendors")
IMPORT_MODES = ("add", "update", "add_update")
IMPORT_MATCHES = ("tag", "serial_number", "product", "name")
IMPORT_STATUSES = ("queued", "running", "checked", "done", "failed")
_JSON = postgresql.JSONB(astext_type=sa.Text())


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _timestamp(name: str) -> "sa.Column[datetime]":
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _entity() -> list["sa.Column[Any]"]:  # Any: uuid, time and integer columns together
    return [
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
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


def _finish(table: str) -> None:
    enable_tenant_rls(table)
    grant_app(table, ("SELECT", "INSERT", "UPDATE"))  # removal is a soft delete
    enable_actor_audit(table)


def _bulk_jobs() -> None:
    table = "asset_bulk_jobs"
    op.create_table(
        table,
        *_entity(),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("changes", _JSON, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("asset_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("status", sa.String(20), server_default="queued", nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("done_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("results", _JSON, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_in("action", BULK_ACTIONS), name=op.f(f"ck_{table}_action")),
        sa.CheckConstraint(_in("status", BULK_STATUSES), name=op.f(f"ck_{table}_status")),
        sa.CheckConstraint(
            f"cardinality(asset_ids) BETWEEN 1 AND {BULK_MAX}", name=op.f(f"ck_{table}_limit")
        ),
        sa.CheckConstraint("total = cardinality(asset_ids)", name=op.f(f"ck_{table}_total")),
        sa.CheckConstraint("processed BETWEEN 0 AND total", name=op.f(f"ck_{table}_processed")),
        _tenant_fk(table),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    )
    op.create_index(
        "ix_asset_bulk_jobs_requested", table, ["tenant_id", "created_by", "created_at"]
    )
    op.create_index(
        "ix_asset_bulk_jobs_pending",
        table,
        ["tenant_id", "created_at"],
        postgresql_where=sa.text("status IN ('queued', 'running') AND deleted_at IS NULL"),
    )
    _finish(table)


def _merges() -> None:
    table = "asset_merges"
    op.create_table(
        table,
        *_entity(),
        sa.Column("survivor_id", sa.Uuid(), nullable=False),
        sa.Column("merged_id", sa.Uuid(), nullable=False),
        sa.Column("merged_tag", sa.String(120), nullable=True),
        sa.Column("merged_serial", sa.String(120), nullable=True),
        sa.Column("merged_barcode", sa.String(120), nullable=True),
        sa.Column("mapping", _JSON, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restored_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("survivor_id <> merged_id", name=op.f(f"ck_{table}_two_assets")),
        sa.CheckConstraint("jsonb_typeof(mapping) = 'array'", name=op.f(f"ck_{table}_mapping")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "survivor_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_asset_merges_survivor",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "merged_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_asset_merges_merged",
        ),
        _tenant_fk(table),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    )
    op.create_index(
        "uq_asset_merges_merged",
        table,
        ["tenant_id", "merged_id"],
        unique=True,
        postgresql_where=sa.text("restored_at IS NULL AND deleted_at IS NULL"),
    )
    op.create_index("ix_asset_merges_survivor", table, ["tenant_id", "survivor_id"])
    for column, name in (
        ("merged_tag", "tag"),
        ("merged_serial", "serial"),
        ("merged_barcode", "barcode"),
    ):
        op.create_index(
            f"ix_asset_merges_{name}", table, ["tenant_id", sa.text(f"lower({column})")]
        )
    _finish(table)


def _imports() -> None:
    table = "asset_imports"
    op.create_table(
        table,
        *_entity(),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("match_on", sa.String(20), nullable=False),
        sa.Column("dry_run", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_format", sa.String(10), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(20), server_default="queued", nullable=False),
        sa.Column("total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("problems", _JSON, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("failure", sa.String(50), nullable=True),
        sa.Column("failure_detail", sa.String(100), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_in("kind", IMPORT_KINDS), name=op.f(f"ck_{table}_kind")),
        sa.CheckConstraint(_in("mode", IMPORT_MODES), name=op.f(f"ck_{table}_mode")),
        sa.CheckConstraint(_in("match_on", IMPORT_MATCHES), name=op.f(f"ck_{table}_match_on")),
        sa.CheckConstraint(_in("status", IMPORT_STATUSES), name=op.f(f"ck_{table}_status")),
        sa.CheckConstraint(
            _in("file_format", ("csv", "xlsx")), name=op.f(f"ck_{table}_file_format")
        ),
        sa.CheckConstraint("processed BETWEEN 0 AND total", name=op.f(f"ck_{table}_processed")),
        _tenant_fk(table),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    )
    op.create_index("ix_asset_imports_requested", table, ["tenant_id", "created_by", "created_at"])
    op.create_index(
        "ix_asset_imports_pending",
        table,
        ["tenant_id", "created_at"],
        postgresql_where=sa.text("status IN ('queued', 'running') AND deleted_at IS NULL"),
    )
    _finish(table)


def upgrade() -> None:
    """Adds the bulk-job, merge and import tables."""
    _bulk_jobs()
    _merges()
    _imports()


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_EXISTS = " OR ".join(f"EXISTS (SELECT 1 FROM {table})" for table in NEW_TABLES)  # noqa: S608 - fixed names
_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF {_EXISTS} THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has asset bulk jobs, merges or imports (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def downgrade() -> None:
    """Drops what 0145 added only while no tenant uses it; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY)
    for table in NEW_TABLES:
        op.drop_table(table)
