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
    # Days before a warranty ends that its managers hear of it (0114; Appendix A: 30).
    warranty_notice_days: Mapped[int] = mapped_column(Integer, server_default="30")
    scan_retention_months: Mapped[int] = mapped_column(Integer, server_default="6")
    # Requesters may book loanable assets from the portal (0130; REQ-AST-032 AC3; off by default).
    portal_booking: Mapped[bool] = mapped_column(Boolean, server_default="false")
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
        # Its holder (0111): a person, a department, or the asset it is fitted to.
        ForeignKeyConstraint(
            ["tenant_id", "owner_user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_assets_owner_user",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_asset_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_assets_parent_asset",
        ),
        Index("ix_assets_owner_user", "tenant_id", "owner_user_id"),
        Index("ix_assets_department", "tenant_id", "department_id"),
        Index("ix_assets_parent", "tenant_id", "parent_asset_id"),
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
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column()
    department_id: Mapped[uuid.UUID | None] = mapped_column()
    parent_asset_id: Mapped[uuid.UUID | None] = mapped_column()
    loanable: Mapped[bool] = mapped_column(Boolean, server_default="false")  # 0114
    warranty_noticed_on: Mapped[date | None] = mapped_column(Date)  # the date last noticed
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
        ForeignKeyConstraint(
            ["tenant_id", "approved_by"],
            ["users.tenant_id", "users.id"],
            name="fk_asset_disposals_approver",
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


class AssetAssignment(TenantEntity):
    """One holding of an asset (migration 0111; REQ-AST-019): by whom, from when to when.

    Never rewritten: a new holder ends the current row and starts another. At most one current
    row per asset (a partial unique index). A disputed acknowledgement leaves it as it is.
    """

    __tablename__ = "asset_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_asset_assignments_asset",
        ),
        Index("ix_asset_assignments_asset", "tenant_id", "asset_id", "started_at"),
        Index("ix_asset_assignments_holder", "tenant_id", "holder_kind", "holder_id", "started_at"),
        Index(
            "uq_asset_assignments_current",
            "tenant_id",
            "asset_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL AND deleted_at IS NULL"),
        ),
    )

    asset_id: Mapped[uuid.UUID]
    holder_kind: Mapped[str] = mapped_column(String(20))
    holder_id: Mapped[uuid.UUID]
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    source: Mapped[str] = mapped_column(String(20))


class AssetRelationship(TenantEntity):
    """A typed link between two assets (migration 0111; REQ-AST-027), shown from both ends."""

    __tablename__ = "asset_relationships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "from_asset_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_asset_relationships_from",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "to_asset_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_asset_relationships_to",
        ),
        Index(
            "uq_asset_relationships_link",
            "tenant_id",
            "from_asset_id",
            "to_asset_id",
            "kind",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_asset_relationships_to", "tenant_id", "to_asset_id"),
    )

    from_asset_id: Mapped[uuid.UUID]
    to_asset_id: Mapped[uuid.UUID]
    kind: Mapped[str] = mapped_column(String(30))


class AssetAcknowledgement(TenantEntity):
    """A person acknowledges an asset given to them (migration 0112; REQ-AST-023).

    One per holding. A dispute keeps the holding and its history exactly as they are.
    """

    __tablename__ = "asset_acknowledgements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_asset_acknowledgements_asset",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_asset_acknowledgements_user",
        ),
        Index("uq_asset_acknowledgements_assignment", "tenant_id", "assignment_id", unique=True),
        Index("ix_asset_acknowledgements_user", "tenant_id", "user_id", "status"),
    )

    asset_id: Mapped[uuid.UUID]
    assignment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asset_assignments.id"))
    user_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    comment: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(String(20))
    answered_at: Mapped[datetime | None]


class AssetGroup(TenantEntity):
    """A named group of assets (migration 0113; REQ-AST-028): static, or a saved filter."""

    __tablename__ = "asset_groups"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_asset_groups_tenant_id_id"),
        Index(
            "uq_asset_groups_name",
            "tenant_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))
    # Any: a shared filter DSL tree (app/shared/api/filters.py), checked when saved.
    filter: Mapped[Any | None] = mapped_column(
        JSONB(none_as_null=True)
    )  # None is SQL NULL (the kind check)


class AssetGroupMember(TenantKeyed, Base):
    """A static group's member (migration 0113)."""

    __tablename__ = "asset_group_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "group_id"],
            ["asset_groups.tenant_id", "asset_groups.id"],
            name="fk_asset_group_members_group",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_asset_group_members_asset",
        ),
        Index("ix_asset_group_members_asset", "tenant_id", "asset_id"),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    created_by: Mapped[uuid.UUID | None]


class AssetLoan(TenantEntity):
    """A loan of one or more assets to a person (migration 0114; REQ-AST-030).

    0130: its display ID (LN-1; loans made before have none), the department it is lent to (the
    borrower collects it for them), its site, and the booking it was handed over from.
    """

    __tablename__ = "asset_loans"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_asset_loans_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "borrower_id"],
            ["users.tenant_id", "users.id"],
            name="fk_asset_loans_borrower",
        ),
        Index(
            "ix_asset_loans_open_due",
            "tenant_id",
            "due_at",
            postgresql_where=text("closed_at IS NULL AND deleted_at IS NULL"),
        ),
        Index("ix_asset_loans_borrower", "tenant_id", "borrower_id"),
        Index(
            "uq_asset_loans_display_id",
            "tenant_id",
            "display_id",
            unique=True,
            postgresql_where=text("display_id IS NOT NULL"),
        ),
        Index("ix_asset_loans_site_id", "tenant_id", "site_id"),
    )

    borrower_id: Mapped[uuid.UUID]
    display_id: Mapped[str | None] = mapped_column(String(20))
    department_id: Mapped[uuid.UUID | None]
    site_id: Mapped[uuid.UUID | None]
    booking_id: Mapped[uuid.UUID | None]
    starts_at: Mapped[datetime]
    due_at: Mapped[datetime]
    closed_at: Mapped[datetime | None]
    comment: Mapped[str | None] = mapped_column(Text)
    due_noticed_at: Mapped[datetime | None]
    overdue_noticed_at: Mapped[datetime | None]


class AssetLoanItem(TenantEntity):
    """One asset of a loan, and how it came back (migration 0114; REQ-AST-031).

    At most one unreturned item per asset: the database refuses a second open loan.
    """

    __tablename__ = "asset_loan_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "loan_id"],
            ["asset_loans.tenant_id", "asset_loans.id"],
            name="fk_asset_loan_items_loan",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_asset_loan_items_asset",
        ),
        Index(
            "uq_asset_loan_items_out",
            "tenant_id",
            "asset_id",
            unique=True,
            postgresql_where=text("returned_at IS NULL AND deleted_at IS NULL"),
        ),
        Index("ix_asset_loan_items_loan", "tenant_id", "loan_id"),
    )

    loan_id: Mapped[uuid.UUID]
    asset_id: Mapped[uuid.UUID]
    returned_at: Mapped[datetime | None]
    outcome: Mapped[str | None] = mapped_column(String(20))
    return_comment: Mapped[str | None] = mapped_column(Text)


# --- consumables, minimum stock, bookings (migration 0130; WP-049b s1) ------------------------


class AssetConsumable(TenantEntity):
    """A consumable product kept in stock (REQ-AST-033): its batch tracking is fixed when made."""

    __tablename__ = "asset_consumables"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_asset_consumables_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["asset_products.tenant_id", "asset_products.id"],
            name="fk_asset_consumables_product",
        ),
        Index(
            "uq_asset_consumables_product",
            "tenant_id",
            "product_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_asset_consumables_updated", "tenant_id", "updated_at", "id"),
    )

    product_id: Mapped[uuid.UUID]
    batch_tracked: Mapped[bool] = mapped_column(Boolean)
    barcode: Mapped[str | None] = mapped_column(String(120))
    vendor_id: Mapped[uuid.UUID | None]  # procurement's vendor, checked through its interface
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # base currency
    comment: Mapped[str | None] = mapped_column(Text)


class AssetConsumableStock(TenantEntity):
    """How many of a consumable a site holds (REQ-AST-033); never below zero (REQ-AST-034)."""

    __tablename__ = "asset_consumable_stocks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_asset_consumable_stocks_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "consumable_id"],
            ["asset_consumables.tenant_id", "asset_consumables.id"],
            name="fk_asset_consumable_stocks_consumable",
        ),
        Index(
            "uq_asset_consumable_stocks_site",
            "tenant_id",
            "consumable_id",
            "site_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_asset_consumable_stocks_site_id", "tenant_id", "site_id"),
    )

    consumable_id: Mapped[uuid.UUID]
    site_id: Mapped[uuid.UUID | None]
    location: Mapped[str | None] = mapped_column(String(200))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), server_default="0")
    low_alerted_at: Mapped[datetime | None]


class AssetConsumableBatch(TenantEntity):
    """A lot of a batch-tracked consumable at one site (REQ-AST-033 AC2)."""

    __tablename__ = "asset_consumable_batches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_asset_consumable_batches_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "consumable_id"],
            ["asset_consumables.tenant_id", "asset_consumables.id"],
            name="fk_asset_consumable_batches_consumable",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "stock_id"],
            ["asset_consumable_stocks.tenant_id", "asset_consumable_stocks.id"],
            name="fk_asset_consumable_batches_stock",
        ),
        Index(
            "uq_asset_consumable_batches_lot",
            "tenant_id",
            "stock_id",
            text("lower(lot_number)"),
            unique=True,
        ),
        Index("ix_asset_consumable_batches_expiry", "tenant_id", "consumable_id", "expires_on"),
    )

    consumable_id: Mapped[uuid.UUID]
    stock_id: Mapped[uuid.UUID]
    lot_number: Mapped[str] = mapped_column(String(120))
    reference: Mapped[str | None] = mapped_column(String(120))
    manufactured_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), server_default="0")


class AssetConsumableMovement(Base):
    """One line of the stock ledger (REQ-AST-033, 034): append-only, never changed.

    The application role may only read and add rows (0130's grant), so there is no version or
    soft delete. `work_item_id` is the request it was allocated from: only an ID (rule e).
    """

    __tablename__ = "asset_consumable_movements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "consumable_id"],
            ["asset_consumables.tenant_id", "asset_consumables.id"],
            name="fk_asset_consumable_movements_consumable",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "stock_id"],
            ["asset_consumable_stocks.tenant_id", "asset_consumable_stocks.id"],
            name="fk_asset_consumable_movements_stock",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["asset_consumable_batches.tenant_id", "asset_consumable_batches.id"],
            name="fk_asset_consumable_movements_batch",
        ),
        Index(
            "ix_asset_consumable_movements_consumable", "tenant_id", "consumable_id", "created_at"
        ),
        Index(
            "ix_asset_consumable_movements_work_item",
            "tenant_id",
            "work_item_id",
            postgresql_where=text("work_item_id IS NOT NULL"),
        ),
        Index(
            "ix_asset_consumable_movements_recipient", "tenant_id", "recipient_kind", "recipient_id"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), sort_order=-90
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=utc_now
    )  # append-only (no UPDATE grant); the shared rule still holds
    created_by: Mapped[uuid.UUID | None] = mapped_column()
    updated_by: Mapped[uuid.UUID | None] = mapped_column()
    consumable_id: Mapped[uuid.UUID] = mapped_column()
    stock_id: Mapped[uuid.UUID] = mapped_column()
    batch_id: Mapped[uuid.UUID | None] = mapped_column()
    kind: Mapped[str] = mapped_column(String(12))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    balance_after: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    happened_on: Mapped[date] = mapped_column(Date)
    recipient_kind: Mapped[str | None] = mapped_column(String(20))
    recipient_id: Mapped[uuid.UUID | None] = mapped_column()
    work_item_id: Mapped[uuid.UUID | None] = mapped_column()
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    comment: Mapped[str | None] = mapped_column(Text)


class AssetStockRule(TenantEntity):
    """A minimum stock per product type or product, and per site or all sites (REQ-AST-035)."""

    __tablename__ = "asset_stock_rules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "product_type_id"],
            ["asset_product_types.tenant_id", "asset_product_types.id"],
            name="fk_asset_stock_rules_product_type",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["asset_products.tenant_id", "asset_products.id"],
            name="fk_asset_stock_rules_product",
        ),
        Index(
            "uq_asset_stock_rules_target",
            "tenant_id",
            "product_type_id",
            "product_id",
            "site_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    product_type_id: Mapped[uuid.UUID | None]
    product_id: Mapped[uuid.UUID | None]
    site_id: Mapped[uuid.UUID | None]
    min_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    # Any: a JSON array of user IDs (strings), checked by the service when saved.
    notify_user_ids: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    create_purchase_request: Mapped[bool] = mapped_column(Boolean, server_default="false")
    reorder_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))


class AssetBooking(TenantEntity):
    """One asset held ahead for a person, for a period (REQ-AST-032)."""

    __tablename__ = "asset_bookings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_asset_bookings_asset",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "borrower_id"],
            ["users.tenant_id", "users.id"],
            name="fk_asset_bookings_borrower",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "loan_id"],
            ["asset_loans.tenant_id", "asset_loans.id"],
            name="fk_asset_bookings_loan",
        ),
        Index(
            "ix_asset_bookings_asset_open",
            "tenant_id",
            "asset_id",
            "starts_at",
            postgresql_where=text("status = 'booked' AND deleted_at IS NULL"),
        ),
        Index("ix_asset_bookings_borrower", "tenant_id", "borrower_id"),
    )

    asset_id: Mapped[uuid.UUID]
    borrower_id: Mapped[uuid.UUID]
    department_id: Mapped[uuid.UUID | None]
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    status: Mapped[str] = mapped_column(String(20), server_default="booked")
    loan_id: Mapped[uuid.UUID | None]
    channel: Mapped[str] = mapped_column(String(20), server_default="console")
    comment: Mapped[str | None] = mapped_column(Text)
