"""The asset catalogue's tables (migration 0080; parity 07 §1-4; D-141).

Constraint names and indexes live in the migration. These models mirror the columns so the
service can read and write them; the checks are repeated only where the service relies on them.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import Base, TenantEntity, TenantKeyed, utc_now

# Any: localised names, {"en": "...", "ar": "...", "ur": "..."}, checked by the domain.
Names = dict[str, Any]


class AssetLifeCycle(TenantEntity):
    """A set of allowed moves between states (REQ-AST-013)."""

    __tablename__ = "asset_life_cycles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_asset_life_cycles_tenant_id_id"),
    )

    code: Mapped[str] = mapped_column(String(40))  # stable; names are display text only
    names: Mapped[Names] = mapped_column(JSONB)
    is_default: Mapped[bool] = mapped_column(Boolean, server_default="false")


class AssetState(TenantEntity):
    """A state an asset can be in, with its category (REQ-AST-012)."""

    __tablename__ = "asset_states"
    __table_args__ = (UniqueConstraint("tenant_id", "id", name="uq_asset_states_tenant_id_id"),)

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
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column()
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
