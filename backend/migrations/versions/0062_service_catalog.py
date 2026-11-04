"""Service catalog (WP-030 s1, plan D2): categories and the items people request.

Both tenant-scoped with RLS (FORCE) and actor audit; soft delete only (no DELETE grant). An
item's form questions, approval stage and fulfilment plan are JSONB checked by the service
(domain/items.py); names are per language (`{"en": ..., "ar": ..., "ur": ...}`). Same-tenant
foreign keys to the category, the SLA policy, the support group and the default technician.
Expand only, no data step; the downgrade drops both tables.

Revision ID: 0062
Revises: 0059
Created: 2026-11-04
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import enable_actor_audit, enable_tenant_rls, grant_app

revision: str = "0062"
down_revision: str | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUDIENCES = ("everyone", "technicians")
PRIORITIES = ("p1", "p2", "p3", "p4")


def _entity() -> list[sa.Column[Any]]:  # Any: each column has its own type
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _same_tenant(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column],
        [f"{target}.tenant_id", f"{target}.id"],
        name=f"fk_{table}_{column}_{target}",
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    """Create both tables with RLS."""
    op.create_table(
        "service_categories",
        *_entity(),
        sa.Column("names", postgresql.JSONB(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "jsonb_typeof(names) = 'object'", name=op.f("ck_service_categories_names_object")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_service_categories_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_categories")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_service_categories_tenant_id_id"),
    )
    op.create_index(
        "ix_service_categories_tenant_sort", "service_categories", ["tenant_id", "sort_order", "id"]
    )
    enable_tenant_rls("service_categories")
    enable_actor_audit("service_categories")
    grant_app("service_categories", ("SELECT", "INSERT", "UPDATE"))

    op.create_table(
        "catalog_items",
        *_entity(),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("names", postgresql.JSONB(), nullable=False),
        sa.Column("descriptions", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("audience", sa.String(length=20), server_default="everyone", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("questions", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("approval", postgresql.JSONB(), nullable=True),
        sa.Column("plan", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("default_priority", sa.String(length=10), nullable=True),
        sa.Column("requester_sets_priority", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sla_policy_id", sa.Uuid(), nullable=True),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("technician_id", sa.Uuid(), nullable=True),
        sa.Column(
            "technician_after_approval", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("count_approval_time", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("auto_fulfil", sa.Boolean(), server_default="true", nullable=False),
        sa.CheckConstraint(
            "audience IN (" + ", ".join(f"'{a}'" for a in AUDIENCES) + ")",
            name=op.f("ck_catalog_items_audience_code"),
        ),
        sa.CheckConstraint(
            "default_priority IS NULL OR default_priority IN ("
            + ", ".join(f"'{p}'" for p in PRIORITIES)
            + ")",
            name=op.f("ck_catalog_items_default_priority_code"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(names) = 'object'", name=op.f("ck_catalog_items_names_object")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(questions) = 'array' AND jsonb_typeof(plan) = 'array'",
            name=op.f("ck_catalog_items_lists_array"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_catalog_items_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        _same_tenant("catalog_items", "category_id", "service_categories"),
        _same_tenant("catalog_items", "sla_policy_id", "sla_policies"),
        _same_tenant("catalog_items", "group_id", "support_groups"),
        _same_tenant("catalog_items", "technician_id", "users"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_items")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_catalog_items_tenant_id_id"),
    )
    op.create_index(
        "ix_catalog_items_tenant_category", "catalog_items", ["tenant_id", "category_id", "id"]
    )
    op.create_index(
        "ix_catalog_items_tenant_updated", "catalog_items", ["tenant_id", "updated_at", "id"]
    )
    enable_tenant_rls("catalog_items")
    enable_actor_audit("catalog_items")
    grant_app("catalog_items", ("SELECT", "INSERT", "UPDATE"))


def downgrade() -> None:
    """Drop both tables (items first: they point at categories)."""
    op.drop_table("catalog_items")
    op.drop_table("service_categories")
