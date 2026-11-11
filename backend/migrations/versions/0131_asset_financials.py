"""Asset financials, notes and attachments (WP-049b s2; REQ-AST-036..038, 049, 050).

Number 0131 from the coordinator. Expand only, no data step:
- `assets`: `cost_centre` and `gl_code` (REQ-AST-038; free text until WP-054 brings real cost
  centres), and the asset's own depreciation settings (REQ-AST-037): `depreciation_method`
  (a method or `none`; NULL takes the product's), `useful_life_years`, `salvage_value`.
- `asset_costs` (REQ-AST-036): the asset's operational cost lines (move, service, contract,
  other), each with a date, an amount (base currency) and a description. The purchase is the
  asset's own price and tax, so it is no line.
- `asset_notes` (REQ-AST-050): notes on an asset, sanitised rich text, with the people mentioned;
  edited and deleted notes keep their history (`field_changes`), a deleted one stays as a
  "note deleted" line with who and when.
- `asset_valuations`: what reports group (REQ-AST-038 AC2): each asset's book value today and
  its total cost of ownership, refreshed when its money changes and once a day (book values
  move with time). Derived, never edited by a person; the reporting role may read it.
- `file_links.owner_type` gains `asset` (attachments on the asset, REQ-AST-050).

The downgrade refuses while any tenant has a cost line, a note, an asset attachment or an asset
using a new column, per tenant with app.tenant_id set (rule 5h). Valuations are derived:
dropping them loses nothing.

Revision ID: 0131
Revises: 0107
Created: 2026-11-11
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import (
    enable_actor_audit,
    enable_tenant_rls,
    grant_app,
    grant_report,
    revoke_report,
)

if TYPE_CHECKING:
    from datetime import datetime

revision: str = "0131"
down_revision: str | None = "0107"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AMOUNT = sa.Numeric(14, 2)
NEW_TABLES = ("asset_valuations", "asset_notes", "asset_costs")
# Valuations are worked out from the rest (dropping them loses nothing), so only these count.
KEPT_TABLES = ("asset_notes", "asset_costs")
NEW_COLUMNS = (
    "cost_centre",
    "gl_code",
    "depreciation_method",
    "useful_life_years",
    "salvage_value",
)
# The same lists as app/modules/assets/domain/financials.py (DepreciationChoice, CostKind).
CHOICES = (
    "straight_line",
    "declining_balance",
    "double_declining_balance",
    "sum_of_years_digits",
    "none",
)
COST_KINDS = ("move", "service", "contract", "other")
OWNER_TYPES_BEFORE = (
    "owner_type IN ('work_item', 'conversation_entry', 'draft', 'branding', 'kb_article',"
    " 'asset_disposal')"
)
OWNER_TYPES_AFTER = (
    "owner_type IN ('work_item', 'conversation_entry', 'draft', 'branding', 'kb_article',"
    " 'asset_disposal', 'asset')"
)


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


def _asset_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", "asset_id"], ["assets.tenant_id", "assets.id"], name=f"fk_{table}_asset"
    )


def _asset_columns() -> None:
    op.add_column("assets", sa.Column("cost_centre", sa.String(60), nullable=True))
    op.add_column("assets", sa.Column("gl_code", sa.String(40), nullable=True))
    op.add_column("assets", sa.Column("depreciation_method", sa.String(30), nullable=True))
    op.add_column("assets", sa.Column("useful_life_years", sa.Integer(), nullable=True))
    op.add_column("assets", sa.Column("salvage_value", AMOUNT, nullable=True))
    op.create_check_constraint(
        op.f("ck_assets_depreciation_method"),
        "assets",
        f"depreciation_method IS NULL OR {_in('depreciation_method', CHOICES)}",
    )
    op.create_check_constraint(
        op.f("ck_assets_useful_life_years"),
        "assets",
        "useful_life_years IS NULL OR useful_life_years BETWEEN 1 AND 100",
    )
    op.create_check_constraint(
        op.f("ck_assets_salvage_value"), "assets", "salvage_value IS NULL OR salvage_value >= 0"
    )
    # Reports group by cost centre (REQ-AST-038 AC2).
    op.create_index("ix_assets_cost_centre", "assets", ["tenant_id", "cost_centre"])


def _costs() -> None:
    op.create_table(
        "asset_costs",
        *_entity(),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("incurred_on", sa.Date(), nullable=False),
        sa.Column("amount", AMOUNT, nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.CheckConstraint(_in("kind", COST_KINDS), name=op.f("ck_asset_costs_kind")),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_asset_costs_amount")),
        sa.CheckConstraint(
            "description IS NULL OR length(description) BETWEEN 1 AND 500",
            name=op.f("ck_asset_costs_description"),
        ),
        _tenant_fk("asset_costs"),
        _asset_fk("asset_costs"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_costs")),
    )
    op.create_index(
        "ix_asset_costs_asset",
        "asset_costs",
        ["tenant_id", "asset_id", "incurred_on"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    enable_tenant_rls("asset_costs")
    grant_app("asset_costs", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("asset_costs")


def _notes() -> None:
    op.create_table(
        "asset_notes",
        *_entity(),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "mentioned_ids", postgresql.ARRAY(sa.Uuid()), server_default="{}", nullable=False
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("length(body) BETWEEN 1 AND 100000", name=op.f("ck_asset_notes_body")),
        _tenant_fk("asset_notes"),
        _asset_fk("asset_notes"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_notes")),
    )
    op.create_index(
        "ix_asset_notes_asset", "asset_notes", ["tenant_id", "asset_id", "created_at", "id"]
    )
    enable_tenant_rls("asset_notes")
    grant_app("asset_notes", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("asset_notes")


def _valuations() -> None:
    op.create_table(
        "asset_valuations",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("book_value", AMOUNT, nullable=True),
        sa.Column("total_cost", AMOUNT, nullable=False),
        sa.Column("valued_on", sa.Date(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        _tenant_fk("asset_valuations"),
        _asset_fk("asset_valuations"),
        sa.PrimaryKeyConstraint("tenant_id", "asset_id", name=op.f("pk_asset_valuations")),
    )
    op.create_index("ix_asset_valuations_valued_on", "asset_valuations", ["tenant_id", "valued_on"])
    enable_tenant_rls("asset_valuations")
    grant_app("asset_valuations", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("asset_valuations")
    grant_report("asset_valuations")


def upgrade() -> None:
    _asset_columns()
    _costs()
    _notes()
    _valuations()
    op.drop_constraint(op.f("ck_file_links_owner_type"), "file_links", type_="check")
    op.create_check_constraint(op.f("ck_file_links_owner_type"), "file_links", OWNER_TYPES_AFTER)


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_EXISTS = " OR ".join(f"EXISTS (SELECT 1 FROM {table})" for table in KEPT_TABLES)  # noqa: S608 - fixed names
_USED = " OR ".join(f"{column} IS NOT NULL" for column in NEW_COLUMNS)
_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF {_EXISTS}
           OR EXISTS (SELECT 1 FROM assets WHERE {_USED})
           OR EXISTS (SELECT 1 FROM file_links WHERE owner_type = 'asset') THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has asset costs, notes, files or financial settings (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def downgrade() -> None:
    """Drops what 0131 added only while no tenant uses it; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_constraint(op.f("ck_file_links_owner_type"), "file_links", type_="check")
    op.create_check_constraint(op.f("ck_file_links_owner_type"), "file_links", OWNER_TYPES_BEFORE)
    revoke_report("asset_valuations")
    for table in NEW_TABLES:
        op.drop_table(table)
    op.drop_index("ix_assets_cost_centre", table_name="assets")
    for name in ("salvage_value", "useful_life_years", "depreciation_method"):
        op.drop_constraint(op.f(f"ck_assets_{name}"), "assets", type_="check")
    for column in reversed(NEW_COLUMNS):
        op.drop_column("assets", column)
