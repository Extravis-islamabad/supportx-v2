"""Assets catalogue (WP-049a session 1; parity 07 §1-4; D-141): product types, products, states,
life cycles and their transitions, and the tenant's asset settings.

- **Product types:** a tree (parent_id), each with an `it` / `non_it` category (D-141: only IT
  assets count toward the licence's asset limit) and a kind (`asset`, `component`, `consumable`).
- **Products:** belong to a type. Their price and tax are stored apart (D-141), with depreciation
  defaults.
- **States:** each has a category, one of in_stock, in_use, in_repair, retired, disposed.
- **Life cycles:** name the allowed moves between states, each optionally needing a reason.
- **Settings:** one row per tenant once an admin saves. `cost_includes_tax` is on by default
  (D-141).

Every table is tenant-scoped with RLS (FORCE). Composite same-tenant foreign keys; soft delete
only (no DELETE grant) except transitions, which an edit replaces. No data step: each tenant's
defaults (Appendix A) are made the first time its catalogue is used (assets.service.defaults).

Revision ID: 0080
Revises: 0069 (main's head; re-pointed if another migration lands first)
Created: 2026-11-05
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

if TYPE_CHECKING:
    from datetime import datetime

revision: str = "0080"
down_revision: str | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATE_CATEGORIES = ("in_stock", "in_use", "in_repair", "retired", "disposed")
DEPRECIATION = (
    "straight_line",
    "declining_balance",
    "double_declining_balance",
    "sum_of_years_digits",
)


def _timestamp(name: str) -> "sa.Column[datetime]":
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


# Any: the columns differ in Python type (UUID, datetime, int); SQLAlchemy's Column is invariant.
def _entity_columns() -> list["sa.Column[Any]"]:
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


def _same_tenant(table: str, column: str, target: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column], [f"{target}.tenant_id", f"{target}.id"], name=f"fk_{table}_{name}"
    )


def _names_check(table: str) -> sa.CheckConstraint:
    # {"en": "...", "ar": "...", "ur": "..."}: English always, every name at most 120 characters.
    return sa.CheckConstraint(
        "jsonb_typeof(names) = 'object' AND names ? 'en'"
        " AND length(names->>'en') BETWEEN 1 AND 120",
        name=op.f(f"ck_{table}_names"),
    )


def _finish(table: str, privileges: tuple[str, ...] = ("SELECT", "INSERT", "UPDATE")) -> None:
    enable_tenant_rls(table)
    grant_app(table, privileges)
    enable_actor_audit(table)


def upgrade() -> None:
    op.create_table(
        "asset_life_cycles",
        *_entity_columns(),
        sa.Column("names", postgresql.JSONB(), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        _names_check("asset_life_cycles"),
        _tenant_fk("asset_life_cycles"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_life_cycles")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_asset_life_cycles_tenant_id_id"),
    )
    # At most one default life cycle per tenant.
    op.create_index(
        "uq_asset_life_cycles_default",
        "asset_life_cycles",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default AND deleted_at IS NULL"),
    )
    _finish("asset_life_cycles")

    op.create_table(
        "asset_states",
        *_entity_columns(),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("names", postgresql.JSONB(), nullable=False),
        sa.Column("category", sa.String(12), nullable=False),
        sa.Column("reason_required", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_default_for_category", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("system", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sort", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "category IN (" + ", ".join(f"'{c}'" for c in STATE_CATEGORIES) + ")",
            name=op.f("ck_asset_states_category"),
        ),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,39}$'", name=op.f("ck_asset_states_code")),
        _names_check("asset_states"),
        _tenant_fk("asset_states"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_states")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_asset_states_tenant_id_id"),
    )
    op.create_index(
        "uq_asset_states_code",
        "asset_states",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # One default state per category (the automatic moves go there: assign, unassign, return).
    op.create_index(
        "uq_asset_states_category_default",
        "asset_states",
        ["tenant_id", "category"],
        unique=True,
        postgresql_where=sa.text("is_default_for_category AND deleted_at IS NULL"),
    )
    _finish("asset_states")

    op.create_table(
        "asset_life_cycle_transitions",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("life_cycle_id", sa.Uuid(), nullable=False),
        sa.Column("from_state_id", sa.Uuid(), nullable=False),
        sa.Column("to_state_id", sa.Uuid(), nullable=False),
        sa.Column("reason_required", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "required_fields",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("permission", sa.String(80), nullable=True),
        _timestamp("created_at"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "from_state_id <> to_state_id", name=op.f("ck_asset_life_cycle_transitions_move")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(required_fields) = 'array'",
            name=op.f("ck_asset_life_cycle_transitions_required_fields"),
        ),
        _tenant_fk("asset_life_cycle_transitions"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "life_cycle_id"],
            ["asset_life_cycles.tenant_id", "asset_life_cycles.id"],
            name="fk_asset_life_cycle_transitions_life_cycle",
            ondelete="CASCADE",
        ),
        _same_tenant("asset_life_cycle_transitions", "from_state_id", "asset_states", "from_state"),
        _same_tenant("asset_life_cycle_transitions", "to_state_id", "asset_states", "to_state"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_life_cycle_transitions")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_asset_life_cycle_transitions_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "life_cycle_id",
            "from_state_id",
            "to_state_id",
            name="uq_asset_life_cycle_transitions_move",
        ),
    )
    enable_tenant_rls("asset_life_cycle_transitions")
    grant_app("asset_life_cycle_transitions", ("SELECT", "INSERT", "DELETE"))

    op.create_table(
        "asset_product_types",
        *_entity_columns(),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("api_name", sa.String(64), nullable=False),
        sa.Column("names", postgresql.JSONB(), nullable=False),
        sa.Column("icon", sa.String(40), nullable=True),
        sa.Column("category", sa.String(6), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("life_cycle_id", sa.Uuid(), nullable=True),
        sa.Column("tag_pattern", sa.String(40), nullable=True),
        sa.Column("ack_required", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sort", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "category IN ('it', 'non_it')", name=op.f("ck_asset_product_types_category")
        ),
        sa.CheckConstraint(
            "kind IN ('asset', 'component', 'consumable')", name=op.f("ck_asset_product_types_kind")
        ),
        sa.CheckConstraint(
            "api_name ~ '^[a-z][a-z0-9_]{1,63}$'", name=op.f("ck_asset_product_types_api_name")
        ),
        sa.CheckConstraint("id <> parent_id", name=op.f("ck_asset_product_types_not_own_parent")),
        _names_check("asset_product_types"),
        _tenant_fk("asset_product_types"),
        _same_tenant("asset_product_types", "parent_id", "asset_product_types", "parent"),
        _same_tenant("asset_product_types", "life_cycle_id", "asset_life_cycles", "life_cycle"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_product_types")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_asset_product_types_tenant_id_id"),
    )
    op.create_index(
        "uq_asset_product_types_api_name",
        "asset_product_types",
        ["tenant_id", "api_name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_asset_product_types_parent", "asset_product_types", ["tenant_id", "parent_id"]
    )
    _finish("asset_product_types")

    op.create_table(
        "asset_products",
        *_entity_columns(),
        sa.Column("product_type_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("manufacturer", sa.String(200), nullable=True),
        sa.Column("part_number", sa.String(100), nullable=True),
        # D-141: price and tax apart; the total is their sum, never stored on its own.
        sa.Column("price", sa.Numeric(14, 2), nullable=True),
        sa.Column("tax", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("gl_code", sa.String(40), nullable=True),
        sa.Column(
            "hide_from_purchase_orders", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("depreciation_method", sa.String(30), nullable=True),
        sa.Column("useful_life_years", sa.Integer(), nullable=True),
        sa.Column("salvage_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 200", name=op.f("ck_asset_products_name")),
        sa.CheckConstraint(
            "(price IS NULL OR price >= 0) AND (tax IS NULL OR tax >= 0)"
            " AND (salvage_value IS NULL OR salvage_value >= 0)",
            name=op.f("ck_asset_products_amounts"),
        ),
        sa.CheckConstraint(
            "currency IS NULL OR currency ~ '^[A-Z]{3}$'", name=op.f("ck_asset_products_currency")
        ),
        sa.CheckConstraint(
            "depreciation_method IS NULL OR depreciation_method IN ("
            + ", ".join(f"'{m}'" for m in DEPRECIATION)
            + ")",
            name=op.f("ck_asset_products_depreciation_method"),
        ),
        sa.CheckConstraint(
            "useful_life_years IS NULL OR useful_life_years BETWEEN 1 AND 100",
            name=op.f("ck_asset_products_useful_life"),
        ),
        _tenant_fk("asset_products"),
        _same_tenant("asset_products", "product_type_id", "asset_product_types", "product_type"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_products")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_asset_products_tenant_id_id"),
    )
    op.create_index("ix_asset_products_type", "asset_products", ["tenant_id", "product_type_id"])
    op.create_index("ix_asset_products_name", "asset_products", ["tenant_id", "name", "id"])
    _finish("asset_products")

    op.create_table(
        "asset_settings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("tag_pattern", sa.String(40), server_default="AST-{n}", nullable=False),
        sa.Column("age_basis", sa.String(20), server_default="acquisition_date", nullable=False),
        sa.Column("cost_includes_tax", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("copy_limit", sa.Integer(), server_default="50", nullable=False),
        sa.Column("site_follows_owner", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("portal_own_assets_only", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("email_include_assets", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("scan_retention_months", sa.Integer(), server_default="6", nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "age_basis IN ('acquisition_date', 'created_date')",
            name=op.f("ck_asset_settings_age_basis"),
        ),
        sa.CheckConstraint(
            "copy_limit BETWEEN 1 AND 500 AND scan_retention_months BETWEEN 1 AND 60",
            name=op.f("ck_asset_settings_ranges"),
        ),
        sa.CheckConstraint("tag_pattern LIKE '%{n}%'", name=op.f("ck_asset_settings_tag_pattern")),
        _tenant_fk("asset_settings"),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_asset_settings")),
    )
    _finish("asset_settings")


def downgrade() -> None:
    for table in (
        "asset_settings",
        "asset_products",
        "asset_product_types",
        "asset_life_cycle_transitions",
        "asset_states",
        "asset_life_cycles",
    ):
        op.drop_table(table)
