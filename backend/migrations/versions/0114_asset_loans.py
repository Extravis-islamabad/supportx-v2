"""Loanable assets, loans and returns; warranty notices (WP-049a s5; REQ-AST-029, 030, 031, 059).

- `assets.loanable` (off for every existing asset) and `assets.warranty_noticed_on`: the warranty
  date a notice was sent for, so each date is noticed once (a changed date is noticed again).
- `asset_settings.warranty_notice_days`: Appendix A's 30 days.
- `asset_loans`: who borrows, from when, due when; when it closed; when its due and overdue
  notices went out (each claimed once, per tenant).
- `asset_loan_items`: the assets of a loan and how each came back. An asset is out on at most
  one loan at a time: a unique partial index on its unreturned item, so two loans racing for it
  can never both be saved (REQ-AST-030 AC3; loans start at once, booking ahead is REQ-AST-032).

The downgrade refuses while any tenant has a loan or a loanable asset (rule 5h).

Revision ID: 0114
Revises: 0113
Created: 2026-11-06
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

if TYPE_CHECKING:
    from datetime import datetime

revision: str = "0114"
down_revision: str | None = "0113"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def upgrade() -> None:
    op.add_column(
        "assets", sa.Column("loanable", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column("assets", sa.Column("warranty_noticed_on", sa.Date(), nullable=True))
    op.add_column(
        "asset_settings",
        sa.Column("warranty_notice_days", sa.Integer(), server_default="30", nullable=False),
    )
    op.create_check_constraint(
        "ck_asset_settings_warranty_notice_days",
        "asset_settings",
        "warranty_notice_days BETWEEN 1 AND 365",
    )

    op.create_table(
        "asset_loans",
        *_entity(),
        sa.Column("borrower_id", sa.Uuid(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("due_noticed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("overdue_noticed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("due_at > starts_at", name=op.f("ck_asset_loans_dates")),
        sa.CheckConstraint(
            "comment IS NULL OR length(comment) BETWEEN 1 AND 2000",
            name=op.f("ck_asset_loans_comment"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_asset_loans_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "borrower_id"],
            ["users.tenant_id", "users.id"],
            name="fk_asset_loans_borrower",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_loans")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_asset_loans_tenant_id_id"),
    )
    op.create_index(
        "ix_asset_loans_open_due",
        "asset_loans",
        ["tenant_id", "due_at"],
        postgresql_where=sa.text("closed_at IS NULL AND deleted_at IS NULL"),
    )
    op.create_index("ix_asset_loans_borrower", "asset_loans", ["tenant_id", "borrower_id"])
    enable_tenant_rls("asset_loans")
    grant_app("asset_loans", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("asset_loans")

    op.create_table(
        "asset_loan_items",
        *_entity(),
        sa.Column("loan_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=True),
        sa.Column("return_comment", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('in_stock', 'in_repair')",
            name=op.f("ck_asset_loan_items_outcome"),
        ),
        sa.CheckConstraint(
            "(returned_at IS NULL) = (outcome IS NULL)", name=op.f("ck_asset_loan_items_returned")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_asset_loan_items_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "loan_id"],
            ["asset_loans.tenant_id", "asset_loans.id"],
            name="fk_asset_loan_items_loan",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_asset_loan_items_asset",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_loan_items")),
    )
    # One open loan per asset, enforced by the database (REQ-AST-030 AC3).
    op.create_index(
        "uq_asset_loan_items_out",
        "asset_loan_items",
        ["tenant_id", "asset_id"],
        unique=True,
        postgresql_where=sa.text("returned_at IS NULL AND deleted_at IS NULL"),
    )
    op.create_index("ix_asset_loan_items_loan", "asset_loan_items", ["tenant_id", "loan_id"])
    enable_tenant_rls("asset_loan_items")
    grant_app("asset_loan_items", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("asset_loan_items")


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM asset_loans)
           OR EXISTS (SELECT 1 FROM assets WHERE loanable OR warranty_noticed_on IS NOT NULL) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has loans or loanable assets (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drops what 0114 added only while no tenant uses it; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_table("asset_loan_items")
    op.drop_table("asset_loans")
    op.drop_constraint("ck_asset_settings_warranty_notice_days", "asset_settings", type_="check")
    op.drop_column("asset_settings", "warranty_notice_days")
    op.drop_column("assets", "warranty_noticed_on")
    op.drop_column("assets", "loanable")
