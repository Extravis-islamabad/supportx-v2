"""The asset record (WP-049a session 2; parity 07 §3, REQ-AST-007, 008).

One tenant-scoped table with RLS (FORCE), soft delete only (no DELETE grant):
- product, its type (kept on the asset: fields and the licence count go by it) and state, with
  same-tenant foreign keys to the catalogue;
- tag, serial, discovered serial and barcode. Tag and serial are unique per tenant ignoring
  case, trash included, so a restored asset never collides and a tag is never reused;
- vendor, site and purchase order as plain IDs (other modules' records, checked through their
  interfaces);
- price and tax apart (D-141), dates, location, description;
- `custom` JSONB with its text for search, and generated search columns (the WP-027 engine).

The downgrade drops the table only while no tenant has an asset (rule 5h).

Revision ID: 0082
Revises: 0081
Created: 2026-11-05
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

if TYPE_CHECKING:
    from datetime import datetime

revision: str = "0082"
down_revision: str | None = "0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The same expressions as app/modules/assets/infra/models.py (the model test compares them).
_IDENTIFIERS = (
    "coalesce(tag, '') || ' ' || coalesce(serial_number, '') || ' '"
    " || coalesce(discovered_serial, '') || ' ' || coalesce(barcode, '')"
)
# The parser reads "AST-12" as "ast" and the number "-12": identifiers and custom text go in
# again with their separators as spaces, so "12" and "AST-12" both find it.
_SPLIT = "'[-./:#_]+'"
SEARCH_VECTOR = (
    f"sx_search_vector(name || ' ' || {_IDENTIFIERS} || ' '"
    f" || regexp_replace({_IDENTIFIERS}, {_SPLIT}, ' ', 'g'),"
    " coalesce(description, '') || ' ' || coalesce(custom_text, '') || ' '"
    f" || regexp_replace(coalesce(custom_text, ''), {_SPLIT}, ' ', 'g'))"
)
SEARCH_TEXT = f"sx_search_normalize(name || ' ' || {_IDENTIFIERS})"


def _timestamp(name: str) -> "sa.Column[datetime]":
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _same_tenant(column: str, target: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column], [f"{target}.tenant_id", f"{target}.id"], name=f"fk_assets_{name}"
    )


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("product_type_id", sa.Uuid(), nullable=False),
        sa.Column("state_id", sa.Uuid(), nullable=False),
        sa.Column("tag", sa.String(120), nullable=True),
        sa.Column("serial_number", sa.String(120), nullable=True),
        sa.Column("discovered_serial", sa.String(120), nullable=True),
        sa.Column("barcode", sa.String(120), nullable=True),
        sa.Column("vendor_id", sa.Uuid(), nullable=True),
        sa.Column("site_id", sa.Uuid(), nullable=True),
        sa.Column("location", sa.String(200), nullable=True),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=True),
        sa.Column("purchase_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("purchase_tax", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("acquired_on", sa.Date(), nullable=True),
        sa.Column("warranty_expires_on", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "custom", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("custom_text", sa.Text(), nullable=True),
        sa.Column(
            "search_vector", postgresql.TSVECTOR(), sa.Computed(SEARCH_VECTOR, persisted=True)
        ),
        sa.Column("search_text", sa.Text(), sa.Computed(SEARCH_TEXT, persisted=True)),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 200", name=op.f("ck_assets_name")),
        sa.CheckConstraint(
            "currency IS NULL OR currency ~ '^[A-Z]{3}$'", name=op.f("ck_assets_currency")
        ),
        sa.CheckConstraint(
            "(purchase_price IS NULL OR purchase_price >= 0)"
            " AND (purchase_tax IS NULL OR purchase_tax >= 0)",
            name=op.f("ck_assets_amounts"),
        ),
        sa.CheckConstraint("jsonb_typeof(custom) = 'object'", name=op.f("ck_assets_custom")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_assets_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        _same_tenant("product_id", "asset_products", "product"),
        _same_tenant("product_type_id", "asset_product_types", "product_type"),
        _same_tenant("state_id", "asset_states", "state"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assets")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_assets_tenant_id_id"),
    )
    op.create_index("uq_assets_tag", "assets", ["tenant_id", sa.text("lower(tag)")], unique=True)
    op.create_index(
        "uq_assets_serial", "assets", ["tenant_id", sa.text("lower(serial_number)")], unique=True
    )
    op.create_index("ix_assets_updated", "assets", ["tenant_id", "updated_at", "id"])
    op.create_index("ix_assets_type", "assets", ["tenant_id", "product_type_id"])
    op.create_index("ix_assets_state", "assets", ["tenant_id", "state_id"])
    op.create_index("ix_assets_vendor", "assets", ["tenant_id", "vendor_id"])
    op.create_index("ix_assets_site", "assets", ["tenant_id", "site_id"])
    op.create_index("ix_assets_search_vector", "assets", ["search_vector"], postgresql_using="gin")
    op.create_index(
        "ix_assets_search_text",
        "assets",
        ["search_text"],
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )
    op.create_index("ix_assets_custom", "assets", ["custom"], postgresql_using="gin")
    enable_tenant_rls("assets")
    grant_app("assets", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("assets")


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY_ASSET = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM assets) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has assets (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drops the table only while no tenant has an asset; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY_ASSET)
    op.drop_table("assets")
