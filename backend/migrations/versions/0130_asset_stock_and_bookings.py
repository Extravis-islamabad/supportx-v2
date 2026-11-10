"""Consumable stock, minimum-stock rules, bookings ahead, the loan's leftovers (WP-049b s1).

Number 0130 from the coordinator. Expand only, no data step:
- `asset_consumables` (REQ-AST-033): a product of a consumable type kept in stock, with its
  barcode, vendor, unit cost and comments. Batch tracking is chosen when it is made and never
  switched afterwards (AC3; the service refuses, the column is kept as made).
- `asset_consumable_stocks`: the quantity per consumable and site (a NULL site is "no site", one
  row either way: NULLS NOT DISTINCT), never below zero (a CHECK). `low_alerted_at` is when its
  minimum-stock alert went out; cleared when stock rises above the minimum (REQ-AST-035 AC1).
- `asset_consumable_batches`: a batch-tracked consumable's lots at a site, with their
  manufacture and expiry dates and quantities (never below zero).
- `asset_consumable_movements`: the append-only ledger (receive, allocate, adjust, return): how
  much, the balance after, who and why, the recipient of an allocation (a person, a department or
  an asset) and the request it was made from. A request is only an ID (rule e: no foreign key to
  work items). The application may only read and add rows.
- `asset_stock_rules` (REQ-AST-035): a minimum per product type or product, and per site or all
  sites, with the people told and the optional draft purchase request (WP-054).
- `asset_bookings` (REQ-AST-032): one asset held for a period for a person (and their
  department), booked, handed over (then its loan) or cancelled.
- `asset_loans` (REQ-AST-030's leftovers): `display_id` (LN-1, new loans; older loans keep none),
  `department_id` (lent to a department, collected by the borrower), `site_id`, `booking_id`.
- `asset_settings.portal_booking`: requesters may book from the portal (off by default).

The downgrade refuses while any tenant has a row in a new table, a loan using a new column, or
portal booking on (rule 5h).

Revision ID: 0130
Revises: 0128
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

revision: str = "0130"
down_revision: str | None = "0128"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUANTITY = sa.Numeric(14, 3)
AMOUNT = sa.Numeric(14, 2)
NEW_TABLES = (
    "asset_bookings",
    "asset_stock_rules",
    "asset_consumable_movements",
    "asset_consumable_batches",
    "asset_consumable_stocks",
    "asset_consumables",
)


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


def _finish(table: str, privileges: tuple[str, ...] = ("SELECT", "INSERT", "UPDATE")) -> None:
    enable_tenant_rls(table)
    grant_app(table, privileges)
    enable_actor_audit(table)


def _consumables() -> None:
    op.create_table(
        "asset_consumables",
        *_entity(),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("batch_tracked", sa.Boolean(), nullable=False),
        sa.Column("barcode", sa.String(120), nullable=True),
        sa.Column("vendor_id", sa.Uuid(), nullable=True),
        sa.Column("unit_cost", AMOUNT, nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "unit_cost IS NULL OR unit_cost >= 0", name=op.f("ck_asset_consumables_cost")
        ),
        sa.CheckConstraint(
            "comment IS NULL OR length(comment) BETWEEN 1 AND 2000",
            name=op.f("ck_asset_consumables_comment"),
        ),
        _tenant_fk("asset_consumables"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["asset_products.tenant_id", "asset_products.id"],
            name="fk_asset_consumables_product",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_consumables")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_asset_consumables_tenant_id_id"),
    )
    op.create_index(
        "uq_asset_consumables_product",
        "asset_consumables",
        ["tenant_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_asset_consumables_updated", "asset_consumables", ["tenant_id", "updated_at", "id"]
    )
    _finish("asset_consumables")

    op.create_table(
        "asset_consumable_stocks",
        *_entity(),
        sa.Column("consumable_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=True),
        sa.Column("location", sa.String(200), nullable=True),
        sa.Column("quantity", QUANTITY, server_default="0", nullable=False),
        sa.Column("low_alerted_at", sa.DateTime(timezone=True), nullable=True),
        # Never below zero (REQ-AST-034): an allocation that would go below is refused.
        sa.CheckConstraint("quantity >= 0", name=op.f("ck_asset_consumable_stocks_quantity")),
        _tenant_fk("asset_consumable_stocks"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "consumable_id"],
            ["asset_consumables.tenant_id", "asset_consumables.id"],
            name="fk_asset_consumable_stocks_consumable",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_consumable_stocks")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_asset_consumable_stocks_tenant_id_id"),
    )
    # One row per consumable and site; "no site" is one row too.
    op.create_index(
        "uq_asset_consumable_stocks_site",
        "asset_consumable_stocks",
        ["tenant_id", "consumable_id", "site_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "ix_asset_consumable_stocks_site_id", "asset_consumable_stocks", ["tenant_id", "site_id"]
    )
    _finish("asset_consumable_stocks")

    op.create_table(
        "asset_consumable_batches",
        *_entity(),
        sa.Column("consumable_id", sa.Uuid(), nullable=False),
        sa.Column("stock_id", sa.Uuid(), nullable=False),
        sa.Column("lot_number", sa.String(120), nullable=False),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("manufactured_on", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("quantity", QUANTITY, server_default="0", nullable=False),
        sa.CheckConstraint("quantity >= 0", name=op.f("ck_asset_consumable_batches_quantity")),
        sa.CheckConstraint(
            "manufactured_on IS NULL OR expires_on IS NULL OR expires_on >= manufactured_on",
            name=op.f("ck_asset_consumable_batches_dates"),
        ),
        _tenant_fk("asset_consumable_batches"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "consumable_id"],
            ["asset_consumables.tenant_id", "asset_consumables.id"],
            name="fk_asset_consumable_batches_consumable",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "stock_id"],
            ["asset_consumable_stocks.tenant_id", "asset_consumable_stocks.id"],
            name="fk_asset_consumable_batches_stock",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_consumable_batches")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_asset_consumable_batches_tenant_id_id"),
    )
    op.create_index(
        "uq_asset_consumable_batches_lot",
        "asset_consumable_batches",
        ["tenant_id", "stock_id", sa.text("lower(lot_number)")],
        unique=True,
    )
    op.create_index(
        "ix_asset_consumable_batches_expiry",
        "asset_consumable_batches",
        ["tenant_id", "consumable_id", "expires_on"],
    )
    _finish("asset_consumable_batches")

    op.create_table(
        "asset_consumable_movements",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("consumable_id", sa.Uuid(), nullable=False),
        sa.Column("stock_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("quantity", QUANTITY, nullable=False),
        sa.Column("balance_after", QUANTITY, nullable=False),
        sa.Column("happened_on", sa.Date(), nullable=False),
        sa.Column("recipient_kind", sa.String(20), nullable=True),
        sa.Column("recipient_id", sa.Uuid(), nullable=True),
        sa.Column("work_item_id", sa.Uuid(), nullable=True),
        sa.Column("unit_cost", AMOUNT, nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('receive', 'allocate', 'adjust', 'return')",
            name=op.f("ck_asset_consumable_movements_kind"),
        ),
        sa.CheckConstraint(
            "quantity <> 0 AND balance_after >= 0",
            name=op.f("ck_asset_consumable_movements_quantity"),
        ),
        # Receipts and returns add, allocations take away; an adjustment either way.
        sa.CheckConstraint(
            "(kind IN ('receive', 'return') AND quantity > 0)"
            " OR (kind = 'allocate' AND quantity < 0) OR kind = 'adjust'",
            name=op.f("ck_asset_consumable_movements_sign"),
        ),
        sa.CheckConstraint(
            "recipient_kind IS NULL OR recipient_kind IN ('user', 'department', 'asset')",
            name=op.f("ck_asset_consumable_movements_recipient_kind"),
        ),
        sa.CheckConstraint(
            "(recipient_kind IS NULL) = (recipient_id IS NULL)"
            " AND (kind <> 'allocate' OR recipient_id IS NOT NULL)",
            name=op.f("ck_asset_consumable_movements_recipient"),
        ),
        sa.CheckConstraint(
            "comment IS NULL OR length(comment) BETWEEN 1 AND 2000",
            name=op.f("ck_asset_consumable_movements_comment"),
        ),
        _tenant_fk("asset_consumable_movements"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "consumable_id"],
            ["asset_consumables.tenant_id", "asset_consumables.id"],
            name="fk_asset_consumable_movements_consumable",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "stock_id"],
            ["asset_consumable_stocks.tenant_id", "asset_consumable_stocks.id"],
            name="fk_asset_consumable_movements_stock",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["asset_consumable_batches.tenant_id", "asset_consumable_batches.id"],
            name="fk_asset_consumable_movements_batch",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_consumable_movements")),
    )
    op.create_index(
        "ix_asset_consumable_movements_consumable",
        "asset_consumable_movements",
        ["tenant_id", "consumable_id", "created_at"],
    )
    op.create_index(
        "ix_asset_consumable_movements_work_item",
        "asset_consumable_movements",
        ["tenant_id", "work_item_id"],
        postgresql_where=sa.text("work_item_id IS NOT NULL"),
    )
    op.create_index(
        "ix_asset_consumable_movements_recipient",
        "asset_consumable_movements",
        ["tenant_id", "recipient_kind", "recipient_id"],
    )
    # Append-only: read and add, never change or remove.
    _finish("asset_consumable_movements", ("SELECT", "INSERT"))


def _rules() -> None:
    op.create_table(
        "asset_stock_rules",
        *_entity(),
        sa.Column("product_type_id", sa.Uuid(), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("site_id", sa.Uuid(), nullable=True),
        sa.Column("min_quantity", QUANTITY, nullable=False),
        sa.Column("notify_user_ids", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column(
            "create_purchase_request", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("reorder_quantity", QUANTITY, nullable=True),
        sa.CheckConstraint(
            "(product_type_id IS NULL) <> (product_id IS NULL)",
            name=op.f("ck_asset_stock_rules_target"),
        ),
        sa.CheckConstraint("min_quantity >= 0", name=op.f("ck_asset_stock_rules_minimum")),
        sa.CheckConstraint(
            "reorder_quantity IS NULL OR reorder_quantity > 0",
            name=op.f("ck_asset_stock_rules_reorder"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(notify_user_ids) = 'array'", name=op.f("ck_asset_stock_rules_notify")
        ),
        _tenant_fk("asset_stock_rules"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_type_id"],
            ["asset_product_types.tenant_id", "asset_product_types.id"],
            name="fk_asset_stock_rules_product_type",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["asset_products.tenant_id", "asset_products.id"],
            name="fk_asset_stock_rules_product",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_stock_rules")),
    )
    # One live rule per target and site (any site is one too).
    op.create_index(
        "uq_asset_stock_rules_target",
        "asset_stock_rules",
        ["tenant_id", "product_type_id", "product_id", "site_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    _finish("asset_stock_rules")


def _bookings() -> None:
    op.create_table(
        "asset_bookings",
        *_entity(),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("borrower_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), server_default="booked", nullable=False),
        sa.Column("loan_id", sa.Uuid(), nullable=True),
        sa.Column("channel", sa.String(20), server_default="console", nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_asset_bookings_dates")),
        sa.CheckConstraint(
            "status IN ('booked', 'handed_over', 'cancelled')",
            name=op.f("ck_asset_bookings_status"),
        ),
        sa.CheckConstraint(
            "(status = 'handed_over') = (loan_id IS NOT NULL)", name=op.f("ck_asset_bookings_loan")
        ),
        sa.CheckConstraint(
            "channel IN ('console', 'portal')", name=op.f("ck_asset_bookings_channel")
        ),
        sa.CheckConstraint(
            "comment IS NULL OR length(comment) BETWEEN 1 AND 2000",
            name=op.f("ck_asset_bookings_comment"),
        ),
        _tenant_fk("asset_bookings"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_asset_bookings_asset",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "borrower_id"],
            ["users.tenant_id", "users.id"],
            name="fk_asset_bookings_borrower",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "loan_id"],
            ["asset_loans.tenant_id", "asset_loans.id"],
            name="fk_asset_bookings_loan",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_bookings")),
    )
    op.create_index(
        "ix_asset_bookings_asset_open",
        "asset_bookings",
        ["tenant_id", "asset_id", "starts_at"],
        postgresql_where=sa.text("status = 'booked' AND deleted_at IS NULL"),
    )
    op.create_index("ix_asset_bookings_borrower", "asset_bookings", ["tenant_id", "borrower_id"])
    _finish("asset_bookings")


def upgrade() -> None:
    op.add_column(
        "asset_settings",
        sa.Column("portal_booking", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("asset_loans", sa.Column("display_id", sa.String(20), nullable=True))
    op.add_column("asset_loans", sa.Column("department_id", sa.Uuid(), nullable=True))
    op.add_column("asset_loans", sa.Column("site_id", sa.Uuid(), nullable=True))
    op.add_column("asset_loans", sa.Column("booking_id", sa.Uuid(), nullable=True))
    op.create_index(
        "uq_asset_loans_display_id",
        "asset_loans",
        ["tenant_id", "display_id"],
        unique=True,
        postgresql_where=sa.text("display_id IS NOT NULL"),
    )
    op.create_index("ix_asset_loans_site_id", "asset_loans", ["tenant_id", "site_id"])
    _consumables()
    _rules()
    _bookings()


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_EXISTS = " OR ".join(f"EXISTS (SELECT 1 FROM {table})" for table in NEW_TABLES)  # noqa: S608 - fixed names
_REFUSE_IF_ANY = f"""
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF {_EXISTS}
           OR EXISTS (SELECT 1 FROM asset_loans WHERE display_id IS NOT NULL
                      OR department_id IS NOT NULL OR site_id IS NOT NULL OR booking_id IS NOT NULL)
           OR EXISTS (SELECT 1 FROM asset_settings WHERE portal_booking) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has stock, bookings or new loan data (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""  # noqa: S608 - fixed table names, no input


def downgrade() -> None:
    """Drops what 0130 added only while no tenant uses it; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY)
    for table in NEW_TABLES:
        op.drop_table(table)
    op.drop_index("ix_asset_loans_site_id", table_name="asset_loans")
    op.drop_index("uq_asset_loans_display_id", table_name="asset_loans")
    for column in ("booking_id", "site_id", "department_id", "display_id"):
        op.drop_column("asset_loans", column)
    op.drop_column("asset_settings", "portal_booking")
