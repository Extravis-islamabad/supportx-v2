"""The asset catalogue's tables (migration 0080; parity 07 §1-4; D-141).

Constraint names and indexes live in the migration. These models mirror the columns so the
service can read and write them; the checks are repeated only where the service relies on them.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Computed,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, Unmapped, mapped_column, unmapped_column

from app.shared.db.models import Base, TenantEntity, TenantKeyed, utc_now

# Any: localised names, {"en": "...", "ar": "...", "ur": "..."}, checked by the domain.
Names = dict[str, Any]


class AssetLifeCycle(TenantEntity):
    """A set of allowed moves between states (REQ-AST-013)."""

    __tablename__ = "asset_life_cycles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_asset_life_cycles_tenant_id_id"),
        Index(
            "uq_asset_life_cycles_code",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # At most one default life cycle per tenant.
        Index(
            "uq_asset_life_cycles_default",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_default AND deleted_at IS NULL"),
        ),
    )

    code: Mapped[str] = mapped_column(String(40))  # stable; names are display text only
    names: Mapped[Names] = mapped_column(JSONB)
    is_default: Mapped[bool] = mapped_column(Boolean, server_default="false")


class AssetState(TenantEntity):
    """A state an asset can be in, with its category (REQ-AST-012)."""

    __tablename__ = "asset_states"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_asset_states_tenant_id_id"),
        Index(
            "uq_asset_states_code",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # One default state per category (the automatic moves go there).
        Index(
            "uq_asset_states_category_default",
            "tenant_id",
            "category",
            unique=True,
            postgresql_where=text("is_default_for_category AND deleted_at IS NULL"),
        ),
    )

    code: Mapped[str] = mapped_column(String(40))
    names: Mapped[Names] = mapped_column(JSONB)
    category: Mapped[str] = mapped_column(String(12))
    reason_required: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_default_for_category: Mapped[bool] = mapped_column(Boolean, server_default="false")
    system: Mapped[bool] = mapped_column(Boolean, server_default="false")
    sort: Mapped[int] = mapped_column(Integer, server_default="0")


class AssetLifeCycleTransition(Base):
    """One allowed move of a life cycle; an edit replaces the life cycle's rows."""

    __tablename__ = "asset_life_cycle_transitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "life_cycle_id"],
            ["asset_life_cycles.tenant_id", "asset_life_cycles.id"],
            name="fk_asset_life_cycle_transitions_life_cycle",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "from_state_id"],
            ["asset_states.tenant_id", "asset_states.id"],
            name="fk_asset_life_cycle_transitions_from_state",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "to_state_id"],
            ["asset_states.tenant_id", "asset_states.id"],
            name="fk_asset_life_cycle_transitions_to_state",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_asset_life_cycle_transitions_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "life_cycle_id",
            "from_state_id",
            "to_state_id",
            name="uq_asset_life_cycle_transitions_move",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), sort_order=-90
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    life_cycle_id: Mapped[uuid.UUID] = mapped_column()
    from_state_id: Mapped[uuid.UUID] = mapped_column()
    to_state_id: Mapped[uuid.UUID] = mapped_column()
    reason_required: Mapped[bool] = mapped_column(Boolean, server_default="false")
    required_fields: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    permission: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column()


class AssetProductType(TenantEntity):
    """A node of the product type tree (REQ-AST-002, 003), IT or non-IT (D-141)."""

    __tablename__ = "asset_product_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_asset_product_types_tenant_id_id"),
        Index(
            "uq_asset_product_types_api_name",
            "tenant_id",
            "api_name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_asset_product_types_parent", "tenant_id", "parent_id"),
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["asset_product_types.tenant_id", "asset_product_types.id"],
            name="fk_asset_product_types_parent",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "life_cycle_id"],
            ["asset_life_cycles.tenant_id", "asset_life_cycles.id"],
            name="fk_asset_product_types_life_cycle",
        ),
    )

    parent_id: Mapped[uuid.UUID | None] = mapped_column()
    api_name: Mapped[str] = mapped_column(String(64))
    names: Mapped[Names] = mapped_column(JSONB)
    icon: Mapped[str | None] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(6))
    kind: Mapped[str] = mapped_column(String(12))
    description: Mapped[str | None] = mapped_column(Text)
    life_cycle_id: Mapped[uuid.UUID | None] = mapped_column()
    tag_pattern: Mapped[str | None] = mapped_column(String(40))
    ack_required: Mapped[bool] = mapped_column(Boolean, server_default="false")
    sort: Mapped[int] = mapped_column(Integer, server_default="0")


class AssetProduct(TenantEntity):
    """A product of a type (REQ-AST-005), with its price and tax apart (D-141)."""

    __tablename__ = "asset_products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_asset_products_tenant_id_id"),
        Index("ix_asset_products_type", "tenant_id", "product_type_id"),
        Index("ix_asset_products_name", "tenant_id", "name", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_type_id"],
            ["asset_product_types.tenant_id", "asset_product_types.id"],
            name="fk_asset_products_product_type",
        ),
    )

    product_type_id: Mapped[uuid.UUID] = mapped_column()
    name: Mapped[str] = mapped_column(String(200))
    manufacturer: Mapped[str | None] = mapped_column(String(200))
    part_number: Mapped[str | None] = mapped_column(String(100))
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    tax: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    gl_code: Mapped[str | None] = mapped_column(String(40))
    hide_from_purchase_orders: Mapped[bool] = mapped_column(Boolean, server_default="false")
    depreciation_method: Mapped[str | None] = mapped_column(String(30))
    useful_life_years: Mapped[int | None] = mapped_column(Integer)
    salvage_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    description: Mapped[str | None] = mapped_column(Text)


class AssetSettings(TenantKeyed, Base):
    """One row per tenant once an admin saves; Appendix A's defaults until then (D-041)."""

    __tablename__ = "asset_settings"

    tag_pattern: Mapped[str] = mapped_column(String(40), server_default="AST-{n}")
    age_basis: Mapped[str] = mapped_column(String(20), server_default="acquisition_date")
    cost_includes_tax: Mapped[bool] = mapped_column(Boolean, server_default="true")  # D-141
    copy_limit: Mapped[int] = mapped_column(Integer, server_default="50")
    site_follows_owner: Mapped[bool] = mapped_column(Boolean, server_default="false")
    portal_own_assets_only: Mapped[bool] = mapped_column(Boolean, server_default="true")
    email_include_assets: Mapped[bool] = mapped_column(Boolean, server_default="false")
    scan_retention_months: Mapped[int] = mapped_column(Integer, server_default="6")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=utc_now)
    created_by: Mapped[uuid.UUID | None] = mapped_column()
    updated_by: Mapped[uuid.UUID | None] = mapped_column()
    version: Mapped[int] = mapped_column(default=1, server_default="1")


# Search (WP-027 engine): the name and every identifier, so a serial, tag or barcode finds it.
_IDENTIFIERS = (
    "coalesce(tag, '') || ' ' || coalesce(serial_number, '') || ' '"
    " || coalesce(discovered_serial, '') || ' ' || coalesce(barcode, '')"
)
# The parser reads "AST-12" as "ast" and the number "-12": identifiers and custom text go in
# again with their separators as spaces, so "12" and "AST-12" both find it.
_SPLIT = "'[-./:#_]+'"
ASSET_SEARCH_VECTOR = (
    f"sx_search_vector(name || ' ' || {_IDENTIFIERS} || ' '"
    f" || regexp_replace({_IDENTIFIERS}, {_SPLIT}, ' ', 'g'),"
    " coalesce(description, '') || ' ' || coalesce(custom_text, '') || ' '"
    f" || regexp_replace(coalesce(custom_text, ''), {_SPLIT}, ' ', 'g'))"
)
ASSET_SEARCH_TEXT = f"sx_search_normalize(name || ' ' || {_IDENTIFIERS})"


class Asset(TenantEntity):
    """One asset (WP-049a s2; REQ-AST-007): what the tenant holds, of one product.

    The product's type is kept on the asset too (it decides the fields and whether the asset
    counts toward the plan's limit, D-141), and moves with a product change. Vendor, site and
    purchase order belong to other modules: plain IDs, checked through their interfaces.
    """

    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_assets_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["asset_products.tenant_id", "asset_products.id"],
            name="fk_assets_product",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_type_id"],
            ["asset_product_types.tenant_id", "asset_product_types.id"],
            name="fk_assets_product_type",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "state_id"],
            ["asset_states.tenant_id", "asset_states.id"],
            name="fk_assets_state",
        ),
        # Unique per tenant when filled, ignoring case, trash included: a restored asset never
        # collides, and a deleted asset's tag is never reused (REQ-AST-007, 008).
        Index("uq_assets_tag", "tenant_id", text("lower(tag)"), unique=True),
        Index("uq_assets_serial", "tenant_id", text("lower(serial_number)"), unique=True),
        Index("ix_assets_updated", "tenant_id", "updated_at", "id"),
        Index("ix_assets_type", "tenant_id", "product_type_id"),
        Index("ix_assets_state", "tenant_id", "state_id"),
        Index("ix_assets_vendor", "tenant_id", "vendor_id"),
        Index("ix_assets_site", "tenant_id", "site_id"),
        Index("ix_assets_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_assets_search_text",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
        Index("ix_assets_custom", "custom", postgresql_using="gin"),
    )

    name: Mapped[str] = mapped_column(String(200))
    product_id: Mapped[uuid.UUID] = mapped_column()
    product_type_id: Mapped[uuid.UUID] = mapped_column()
    state_id: Mapped[uuid.UUID] = mapped_column()
    tag: Mapped[str | None] = mapped_column(String(120))
    serial_number: Mapped[str | None] = mapped_column(String(120))
    discovered_serial: Mapped[str | None] = mapped_column(String(120))  # set by discovery only
    barcode: Mapped[str | None] = mapped_column(String(120))
    vendor_id: Mapped[uuid.UUID | None] = mapped_column()
    site_id: Mapped[uuid.UUID | None] = mapped_column()
    location: Mapped[str | None] = mapped_column(String(200))
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column()  # WP-054
    # D-141: price and tax apart; the total is worked out. Currency of both.
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    purchase_tax: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    acquired_on: Mapped[date | None] = mapped_column(Date)
    warranty_expires_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    custom: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    custom_text: Mapped[str | None] = mapped_column(Text)  # custom values as words, for search
    search_vector: Unmapped[Any] = unmapped_column(
        TSVECTOR, Computed(ASSET_SEARCH_VECTOR, persisted=True)
    )
    search_text: Unmapped[str] = unmapped_column(Text, Computed(ASSET_SEARCH_TEXT, persisted=True))


class AssetDisposal(TenantEntity):
    """How an asset was disposed of (migration 0108; REQ-AST-017): one record per asset.

    The approver is a person of the tenant (a same-tenant foreign key to users, as for the
    asset's own references); the certificate is a file linked to this record.
    """

    __tablename__ = "asset_disposals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_asset_disposals_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_asset_disposals_asset",
        ),
        Index("uq_asset_disposals_asset", "tenant_id", "asset_id", unique=True),
        Index("ix_asset_disposals_on", "tenant_id", "disposed_on", "id"),
    )

    asset_id: Mapped[uuid.UUID]
    disposed_on: Mapped[date] = mapped_column(Date)
    method: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    approved_by: Mapped[uuid.UUID | None]
