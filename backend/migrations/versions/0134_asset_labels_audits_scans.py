"""Asset labels, audits, scan history and the overdue-scan rule (WP-049b s3).

REQ-AST-039, 042, 043, 054, 056. Expand only, no data step:
- `asset_label_jobs`: one PDF of labels (assets or vendor codes, at most 500) built by the
  worker, with its progress, the file and why it failed. `asset_label_prints`: every print and
  reprint, append-only (who, when, what, layout, job; the app may only read and add, AC3).
- `asset_audits` (REQ-AST-042): name, technician or self audit, scope (sites, product types,
  asset groups), planned dates, draft -> running -> closed. `asset_audit_auditors`: the named
  auditors. `asset_audit_items` (043): the expected assets, frozen when the audit starts, and the
  unexpected ones found, each with its result, who marked it, how and where it was seen, and
  a self-audit holder's comment when they disputed it.
- `asset_acknowledgements.audit_id`: a self-audit asks each holder again through the
  acknowledgement they already answer (WP-049a); one per holding outside audits, one per holding
  and audit inside them.
- `asset_scans` (REQ-AST-054): append-only scan history (source, type, result, failure reason,
  what changed). The daily clean-up is its only delete (retention: asset settings).
- `assets.last_scanned_at`: the last good scan, kept when old scans are cleaned up.
- `asset_overdue_rules` (REQ-AST-056): one per tenant, off by default; `asset_overdue_runs`:
  what each run changed, append-only.

The downgrade refuses while any tenant has a row in a new table, an audit acknowledgement or a
scanned asset, per tenant with app.tenant_id set (rule 5h).

Revision ID: 0134
Revises: 0133
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

revision: str = "0134"
down_revision: str | None = "0133"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Dropped in this order (children first).
NEW_TABLES = (
    "asset_overdue_runs",
    "asset_overdue_rules",
    "asset_scans",
    "asset_audit_items",
    "asset_audit_auditors",
    "asset_audits",
    "asset_label_prints",
    "asset_label_jobs",
)
# The same lists as app/modules/assets/domain (labels.py, audits.py, scans.py, overdue.py).
LABEL_TARGETS = ("asset", "vendor_code")
LABEL_LAYOUTS = ("cable", "laptop")
SYMBOLOGIES = ("qr", "code128")
JOB_STATUSES = ("running", "ready", "failed")
AUDIT_KINDS = ("technician", "self")
AUDIT_STATES = ("draft", "running", "closed")
ITEM_KINDS = ("expected", "unexpected")
ITEM_RESULTS = ("found", "missing", "wrong_place", "damaged")
MARK_METHODS = ("scanned", "manual")
FIXES = ("move_site", "change_state", "assign")
SCAN_SOURCES = ("agent", "probe", "import")
SCAN_TYPES = ("full", "hardware", "software", "network")
SCAN_RESULTS = ("ok", "failed")
SCAN_FAILURES = (
    "unreachable",
    "credentials_refused",
    "timed_out",
    "agent_error",
    "unsupported",
    "other",
)
OVERDUE_ACTIONS = ("move_state", "trash")
LABELS_MAX = 500  # per job (the coordinator's cap)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _timestamp(name: str) -> "sa.Column[datetime]":
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _stamps() -> list["sa.Column[Any]"]:  # Any: time and uuid columns together
    return [
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
    ]


def _entity() -> list["sa.Column[Any]"]:  # Any: uuid, time and integer columns together
    return [
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_stamps(),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _append_only() -> list["sa.Column[Any]"]:  # Any: uuid and time columns together
    return [
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_stamps(),
    ]


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="RESTRICT",
    )


def _asset_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", "asset_id"], ["assets.tenant_id", "assets.id"], name=f"fk_{table}_asset"
    )


def _audit_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", "audit_id"],
        ["asset_audits.tenant_id", "asset_audits.id"],
        name=f"fk_{table}_audit",
    )


def _finish(table: str, privileges: tuple[str, ...]) -> None:
    enable_tenant_rls(table)
    grant_app(table, privileges)
    enable_actor_audit(table)


def _labels() -> None:
    op.create_table(
        "asset_label_jobs",
        *_entity(),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("target", sa.String(12), nullable=False),
        sa.Column("layout", sa.String(12), nullable=False),
        sa.Column("symbology", sa.String(10), nullable=False),
        sa.Column("language", sa.String(5), nullable=False),
        sa.Column("asset_ids", postgresql.ARRAY(sa.Uuid()), server_default="{}", nullable=False),
        sa.Column("codes", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(10), server_default="running", nullable=False),
        sa.Column("problem", sa.String(60), nullable=True),
        sa.Column("done", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("object_key", sa.String(300), nullable=True),
        sa.Column("reprint_of", sa.Uuid(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_in("target", LABEL_TARGETS), name=op.f("ck_asset_label_jobs_target")),
        sa.CheckConstraint(_in("layout", LABEL_LAYOUTS), name=op.f("ck_asset_label_jobs_layout")),
        sa.CheckConstraint(
            _in("symbology", SYMBOLOGIES), name=op.f("ck_asset_label_jobs_symbology")
        ),
        sa.CheckConstraint(_in("status", JOB_STATUSES), name=op.f("ck_asset_label_jobs_status")),
        sa.CheckConstraint(
            f"item_count BETWEEN 1 AND {LABELS_MAX}", name=op.f("ck_asset_label_jobs_item_count")
        ),
        sa.CheckConstraint("done >= 0", name=op.f("ck_asset_label_jobs_done")),
        _tenant_fk("asset_label_jobs"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_label_jobs")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_asset_label_jobs_tenant_id_id"),
    )
    op.create_index(
        "ix_asset_label_jobs_requested",
        "asset_label_jobs",
        ["tenant_id", "requested_by", "created_at"],
    )
    _finish("asset_label_jobs", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "asset_label_prints",
        *_append_only(),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("target", sa.String(12), nullable=False),
        sa.Column("layout", sa.String(12), nullable=False),
        sa.Column("symbology", sa.String(10), nullable=False),
        sa.Column("asset_ids", postgresql.ARRAY(sa.Uuid()), server_default="{}", nullable=False),
        sa.Column("codes", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("reprint", sa.Boolean(), server_default="false", nullable=False),
        sa.CheckConstraint(_in("target", LABEL_TARGETS), name=op.f("ck_asset_label_prints_target")),
        sa.CheckConstraint(_in("layout", LABEL_LAYOUTS), name=op.f("ck_asset_label_prints_layout")),
        sa.CheckConstraint(
            _in("symbology", SYMBOLOGIES), name=op.f("ck_asset_label_prints_symbology")
        ),
        _tenant_fk("asset_label_prints"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["asset_label_jobs.tenant_id", "asset_label_jobs.id"],
            name="fk_asset_label_prints_job",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_label_prints")),
    )
    op.create_index(
        "ix_asset_label_prints_created", "asset_label_prints", ["tenant_id", "created_at", "id"]
    )
    # Append-only (AC3): the application may read and add print rows, never change them.
    _finish("asset_label_prints", ("SELECT", "INSERT"))


def _audits() -> None:
    op.create_table(
        "asset_audits",
        *_entity(),
        sa.Column("display_id", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("site_ids", postgresql.ARRAY(sa.Uuid()), server_default="{}", nullable=False),
        sa.Column(
            "product_type_ids", postgresql.ARRAY(sa.Uuid()), server_default="{}", nullable=False
        ),
        sa.Column("group_ids", postgresql.ARRAY(sa.Uuid()), server_default="{}", nullable=False),
        sa.Column("planned_start", sa.Date(), nullable=True),
        sa.Column("planned_end", sa.Date(), nullable=True),
        sa.Column("state", sa.String(10), server_default="draft", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_by", sa.Uuid(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 200", name=op.f("ck_asset_audits_name")),
        sa.CheckConstraint(_in("kind", AUDIT_KINDS), name=op.f("ck_asset_audits_kind")),
        sa.CheckConstraint(_in("state", AUDIT_STATES), name=op.f("ck_asset_audits_state")),
        sa.CheckConstraint(
            "planned_end IS NULL OR planned_start IS NULL OR planned_end >= planned_start",
            name=op.f("ck_asset_audits_planned"),
        ),
        sa.CheckConstraint(
            "(state = 'draft') = (started_at IS NULL)", name=op.f("ck_asset_audits_started")
        ),
        sa.CheckConstraint(
            "(state = 'closed') = (closed_at IS NOT NULL)",
            name=op.f("ck_asset_audits_closed"),
        ),
        _tenant_fk("asset_audits"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_audits")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_asset_audits_tenant_id_id"),
    )
    op.create_index(
        "uq_asset_audits_display_id", "asset_audits", ["tenant_id", "display_id"], unique=True
    )
    op.create_index("ix_asset_audits_updated", "asset_audits", ["tenant_id", "updated_at", "id"])
    _finish("asset_audits", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "asset_audit_auditors",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        *_stamps(),
        _tenant_fk("asset_audit_auditors"),
        _audit_fk("asset_audit_auditors"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_asset_audit_auditors_user",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "audit_id", "user_id", name=op.f("pk_asset_audit_auditors")
        ),
    )
    op.create_index(
        "ix_asset_audit_auditors_user", "asset_audit_auditors", ["tenant_id", "user_id"]
    )
    # A link table: who audits is replaced as a set, its history kept on the audit.
    _finish("asset_audit_auditors", ("SELECT", "INSERT", "DELETE"))

    op.create_table(
        "asset_audit_items",
        *_entity(),
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("expected_site_id", sa.Uuid(), nullable=True),
        sa.Column("result", sa.String(12), nullable=True),
        sa.Column("marked_by", sa.Uuid(), nullable=True),
        sa.Column("marked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("method", sa.String(10), nullable=True),
        sa.Column("seen_site_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        # A self-audit's holder who disputed the asset said why (as on the acknowledgement).
        sa.Column("dispute_comment", sa.Text(), nullable=True),
        sa.Column("fix", sa.String(14), nullable=True),
        sa.Column("fixed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fixed_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(_in("kind", ITEM_KINDS), name=op.f("ck_asset_audit_items_kind")),
        sa.CheckConstraint(
            f"result IS NULL OR {_in('result', ITEM_RESULTS)}",
            name=op.f("ck_asset_audit_items_result"),
        ),
        sa.CheckConstraint(
            f"method IS NULL OR {_in('method', MARK_METHODS)}",
            name=op.f("ck_asset_audit_items_method"),
        ),
        sa.CheckConstraint(
            "(result IS NULL) = (marked_at IS NULL)", name=op.f("ck_asset_audit_items_marked")
        ),
        sa.CheckConstraint(
            f"fix IS NULL OR {_in('fix', FIXES)}", name=op.f("ck_asset_audit_items_fix")
        ),
        sa.CheckConstraint(
            "note IS NULL OR length(note) BETWEEN 1 AND 500",
            name=op.f("ck_asset_audit_items_note"),
        ),
        sa.CheckConstraint(
            "dispute_comment IS NULL OR length(dispute_comment) BETWEEN 1 AND 2000",
            name=op.f("ck_asset_audit_items_dispute_comment"),
        ),
        _tenant_fk("asset_audit_items"),
        _audit_fk("asset_audit_items"),
        _asset_fk("asset_audit_items"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_audit_items")),
    )
    op.create_index(
        "uq_asset_audit_items_asset",
        "asset_audit_items",
        ["tenant_id", "audit_id", "asset_id"],
        unique=True,
    )
    op.create_index(
        "ix_asset_audit_items_result", "asset_audit_items", ["tenant_id", "audit_id", "result"]
    )
    _finish("asset_audit_items", ("SELECT", "INSERT", "UPDATE"))


def _self_audit_acknowledgements() -> None:
    op.add_column("asset_acknowledgements", sa.Column("audit_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_asset_acknowledgements_audit",
        "asset_acknowledgements",
        "asset_audits",
        ["tenant_id", "audit_id"],
        ["tenant_id", "id"],
    )
    # One per holding outside audits (as before); one per holding and audit inside them, so each
    # audit asks again (REQ-AST-042 AC2).
    op.drop_index("uq_asset_acknowledgements_assignment", table_name="asset_acknowledgements")
    op.create_index(
        "uq_asset_acknowledgements_assignment",
        "asset_acknowledgements",
        ["tenant_id", "assignment_id"],
        unique=True,
        postgresql_where=sa.text("audit_id IS NULL"),
    )
    op.create_index(
        "uq_asset_acknowledgements_audit",
        "asset_acknowledgements",
        ["tenant_id", "audit_id", "assignment_id"],
        unique=True,
        postgresql_where=sa.text("audit_id IS NOT NULL"),
    )


def _scans() -> None:
    op.add_column("assets", sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_assets_last_scanned",
        "assets",
        ["tenant_id", "last_scanned_at"],
        postgresql_where=sa.text("last_scanned_at IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_table(
        "asset_scans",
        *_append_only(),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("scan_type", sa.String(12), nullable=True),
        sa.Column("result", sa.String(10), nullable=False),
        sa.Column("failure_reason", sa.String(30), nullable=True),
        sa.Column(
            "changes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(_in("source", SCAN_SOURCES), name=op.f("ck_asset_scans_source")),
        sa.CheckConstraint(
            f"scan_type IS NULL OR {_in('scan_type', SCAN_TYPES)}",
            name=op.f("ck_asset_scans_scan_type"),
        ),
        sa.CheckConstraint(_in("result", SCAN_RESULTS), name=op.f("ck_asset_scans_result")),
        sa.CheckConstraint(
            f"(result = 'failed') = (failure_reason IS NOT NULL)"
            f" AND (failure_reason IS NULL OR {_in('failure_reason', SCAN_FAILURES)})",
            name=op.f("ck_asset_scans_failure"),
        ),
        sa.CheckConstraint("jsonb_typeof(changes) = 'array'", name=op.f("ck_asset_scans_changes")),
        _tenant_fk("asset_scans"),
        _asset_fk("asset_scans"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_scans")),
    )
    op.create_index(
        "ix_asset_scans_asset", "asset_scans", ["tenant_id", "asset_id", "scanned_at", "id"]
    )
    op.create_index("ix_asset_scans_scanned", "asset_scans", ["tenant_id", "scanned_at"])
    # Append-only, but for the retention clean-up (REQ-AST-054 AC2): the only hard delete.
    _finish("asset_scans", ("SELECT", "INSERT", "DELETE"))


def _overdue() -> None:
    op.create_table(
        "asset_overdue_rules",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("days", sa.Integer(), server_default="60", nullable=False),
        sa.Column(
            "product_type_ids", postgresql.ARRAY(sa.Uuid()), server_default="{}", nullable=False
        ),
        sa.Column("action", sa.String(12), server_default="move_state", nullable=False),
        sa.Column("state_id", sa.Uuid(), nullable=True),
        *_stamps(),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.CheckConstraint("days BETWEEN 1 AND 3650", name=op.f("ck_asset_overdue_rules_days")),
        sa.CheckConstraint(
            _in("action", OVERDUE_ACTIONS), name=op.f("ck_asset_overdue_rules_action")
        ),
        sa.CheckConstraint(
            "action <> 'move_state' OR state_id IS NOT NULL OR NOT enabled",
            name=op.f("ck_asset_overdue_rules_state"),
        ),
        _tenant_fk("asset_overdue_rules"),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_asset_overdue_rules")),
    )
    _finish("asset_overdue_rules", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "asset_overdue_runs",
        *_append_only(),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(12), nullable=False),
        sa.Column("state_id", sa.Uuid(), nullable=True),
        sa.Column("changed_count", sa.Integer(), nullable=False),
        sa.Column(
            "changed",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            _in("action", OVERDUE_ACTIONS), name=op.f("ck_asset_overdue_runs_action")
        ),
        _tenant_fk("asset_overdue_runs"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_overdue_runs")),
    )
    op.create_index("ix_asset_overdue_runs_ran", "asset_overdue_runs", ["tenant_id", "ran_at"])
    _finish("asset_overdue_runs", ("SELECT", "INSERT"))


def upgrade() -> None:
    _labels()
    _audits()
    _self_audit_acknowledgements()
    _scans()
    _overdue()


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_EXISTS = " OR ".join(f"EXISTS (SELECT 1 FROM {table})" for table in NEW_TABLES)  # noqa: S608 - fixed names
_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF {_EXISTS}
           OR EXISTS (SELECT 1 FROM asset_acknowledgements WHERE audit_id IS NOT NULL)
           OR EXISTS (SELECT 1 FROM assets WHERE last_scanned_at IS NOT NULL) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has asset labels, audits, scans or an overdue-scan rule (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def downgrade() -> None:
    """Drops what 0134 added only while no tenant uses it; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_index("uq_asset_acknowledgements_audit", table_name="asset_acknowledgements")
    op.drop_index("uq_asset_acknowledgements_assignment", table_name="asset_acknowledgements")
    op.create_index(
        "uq_asset_acknowledgements_assignment",
        "asset_acknowledgements",
        ["tenant_id", "assignment_id"],
        unique=True,
    )
    op.drop_constraint(
        "fk_asset_acknowledgements_audit", "asset_acknowledgements", type_="foreignkey"
    )
    op.drop_column("asset_acknowledgements", "audit_id")
    for table in NEW_TABLES:
        op.drop_table(table)
    op.drop_index("ix_assets_last_scanned", table_name="assets")
    op.drop_column("assets", "last_scanned_at")
