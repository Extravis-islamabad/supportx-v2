"""The disposal record of an asset (WP-049a session 3; REQ-AST-017).

One tenant-scoped table with RLS (FORCE): when, why, how (resale, recycling, donation,
destruction, return to the vendor, other), its cost, who approved it, by whom it was recorded.
One record per asset (it is disposed once; a correction edits the record, with its version).
The optional certificate of data wiping or destruction is a file linked to the record, so the
file links' owner types gain `asset_disposal`.

The downgrade refuses while any tenant has a disposal record or a certificate (rule 5h).

Revision ID: 0108
Revises: 0083
Created: 2026-11-06
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

if TYPE_CHECKING:
    from datetime import datetime

revision: str = "0108"
down_revision: str | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The same list as app/modules/assets/domain/assets.py DISPOSAL_METHODS.
METHODS = ("resale", "recycling", "donation", "destruction", "returned_to_vendor", "other")
OWNER_TYPES_BEFORE = (
    "owner_type IN ('work_item', 'conversation_entry', 'draft', 'branding', 'kb_article')"
)
OWNER_TYPES_AFTER = (
    "owner_type IN ('work_item', 'conversation_entry', 'draft', 'branding', 'kb_article',"
    " 'asset_disposal')"
)


def _timestamp(name: str) -> "sa.Column[datetime]":
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "asset_disposals",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("disposed_on", sa.Date(), nullable=False),
        sa.Column("method", sa.String(40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "method IN (" + ", ".join(f"'{m}'" for m in METHODS) + ")",
            name=op.f("ck_asset_disposals_method"),
        ),
        sa.CheckConstraint(
            "length(reason) BETWEEN 1 AND 1000", name=op.f("ck_asset_disposals_reason")
        ),
        sa.CheckConstraint("cost IS NULL OR cost >= 0", name=op.f("ck_asset_disposals_cost")),
        sa.CheckConstraint(
            "currency IS NULL OR currency ~ '^[A-Z]{3}$'", name=op.f("ck_asset_disposals_currency")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_asset_disposals_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["assets.tenant_id", "assets.id"],
            name="fk_asset_disposals_asset",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approved_by"],
            ["users.tenant_id", "users.id"],
            name="fk_asset_disposals_approver",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_disposals")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_asset_disposals_tenant_id_id"),
    )
    op.create_index(
        "uq_asset_disposals_asset", "asset_disposals", ["tenant_id", "asset_id"], unique=True
    )
    op.create_index("ix_asset_disposals_on", "asset_disposals", ["tenant_id", "disposed_on", "id"])
    enable_tenant_rls("asset_disposals")
    grant_app("asset_disposals", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("asset_disposals")
    op.drop_constraint(op.f("ck_file_links_owner_type"), "file_links", type_="check")
    op.create_check_constraint(op.f("ck_file_links_owner_type"), "file_links", OWNER_TYPES_AFTER)


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM asset_disposals)
           OR EXISTS (SELECT 1 FROM file_links WHERE owner_type = 'asset_disposal') THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has disposal records (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drops the table only while no tenant has a disposal record; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY)
    op.drop_constraint(op.f("ck_file_links_owner_type"), "file_links", type_="check")
    op.create_check_constraint(op.f("ck_file_links_owner_type"), "file_links", OWNER_TYPES_BEFORE)
    op.drop_table("asset_disposals")
