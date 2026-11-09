"""Vendors (WP-049a session 2; REQ-PUR-001): the minimal procurement module.

One tenant-scoped table with RLS (FORCE), soft delete only (no DELETE grant). Names are unique
among a tenant's live vendors, ignoring case. No data step.

The downgrade drops the table only while no tenant has a vendor (rule 5h).

Revision ID: 0081
Revises: 0080
Created: 2026-11-05
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

if TYPE_CHECKING:
    from datetime import datetime

revision: str = "0081"
down_revision: str | None = "0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamp(name: str) -> "sa.Column[datetime]":
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "vendors",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("contact_person", sa.String(120), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("phone", sa.String(120), nullable=True),
        sa.Column("fax", sa.String(120), nullable=True),
        sa.Column("website", sa.String(300), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 200", name=op.f("ck_vendors_name")),
        sa.CheckConstraint(
            "currency IS NULL OR currency ~ '^[A-Z]{3}$'", name=op.f("ck_vendors_currency")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_vendors_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vendors")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_vendors_tenant_id_id"),
    )
    op.create_index(
        "uq_vendors_name",
        "vendors",
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_vendors_name", "vendors", ["tenant_id", "name", "id"])
    enable_tenant_rls("vendors")
    grant_app("vendors", ("SELECT", "INSERT", "UPDATE"))
    enable_actor_audit("vendors")


# Each tenant's rows are visible only with its app.tenant_id set (RLS FORCE).
_REFUSE_IF_ANY_VENDOR = """
DO $$
DECLARE t uuid;
BEGIN
    FOR t IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        IF EXISTS (SELECT 1 FROM vendors) THEN
            RAISE EXCEPTION 'downgrade refused: tenant % has vendors (rule 5h)', t;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


def downgrade() -> None:
    """Drops the table only while no tenant has a vendor; otherwise refuses."""
    op.execute(_REFUSE_IF_ANY_VENDOR)
    op.drop_table("vendors")
