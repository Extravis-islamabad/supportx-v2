"""Service catalog tables (migration 0062; WP-030 s1, plan D2)."""

import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.models import TenantEntity


class ServiceCategory(TenantEntity):
    """A group of items in the catalog, named per language."""

    __tablename__ = "service_categories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_service_categories_tenant_id_id"),
        CheckConstraint("jsonb_typeof(names) = 'object'", name="names_object"),
        Index("ix_service_categories_tenant_sort", "tenant_id", "sort_order", "id"),
    )

    # JSONB of language -> text; Any: SQLAlchemy's JSON typing.
    names: Mapped[dict[str, Any]] = mapped_column(JSONB)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")


class CatalogItem(TenantEntity):
    """Something people request, with what it decides for its requests (domain/items.py)."""

    __tablename__ = "catalog_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_catalog_items_tenant_id_id"),
        CheckConstraint("audience IN ('everyone', 'technicians')", name="audience_code"),
        CheckConstraint(
            "default_priority IS NULL OR default_priority IN ('p1', 'p2', 'p3', 'p4')",
            name="default_priority_code",
        ),
        CheckConstraint("jsonb_typeof(names) = 'object'", name="names_object"),
        CheckConstraint(
            "jsonb_typeof(questions) = 'array' AND jsonb_typeof(plan) = 'array'",
            name="lists_array",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["service_categories.tenant_id", "service_categories.id"],
            name="fk_catalog_items_category_id_service_categories",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sla_policy_id"],
            ["sla_policies.tenant_id", "sla_policies.id"],
            name="fk_catalog_items_sla_policy_id_sla_policies",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "group_id"],
            ["support_groups.tenant_id", "support_groups.id"],
            name="fk_catalog_items_group_id_support_groups",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "technician_id"],
            ["users.tenant_id", "users.id"],
            name="fk_catalog_items_technician_id_users",
            ondelete="RESTRICT",
        ),
        Index("ix_catalog_items_tenant_category", "tenant_id", "category_id", "id"),
        Index("ix_catalog_items_tenant_updated", "tenant_id", "updated_at", "id"),
    )

    category_id: Mapped[uuid.UUID | None]
    # JSONB columns: names and descriptions per language, the form's questions, the approval
    # stage and the fulfilment plan, all checked by domain/items.py. Any: SQLAlchemy's JSON typing.
    names: Mapped[dict[str, Any]] = mapped_column(JSONB)
    descriptions: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    audience: Mapped[str] = mapped_column(String(20), server_default="everyone")
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    approval: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    plan: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    default_priority: Mapped[str | None] = mapped_column(String(10))
    requester_sets_priority: Mapped[bool] = mapped_column(Boolean, server_default="false")
    sla_policy_id: Mapped[uuid.UUID | None]
    group_id: Mapped[uuid.UUID | None]
    technician_id: Mapped[uuid.UUID | None]
    technician_after_approval: Mapped[bool] = mapped_column(Boolean, server_default="false")
    count_approval_time: Mapped[bool] = mapped_column(Boolean, server_default="false")
    auto_fulfil: Mapped[bool] = mapped_column(Boolean, server_default="true")


__all__ = ["CatalogItem", "ServiceCategory"]
