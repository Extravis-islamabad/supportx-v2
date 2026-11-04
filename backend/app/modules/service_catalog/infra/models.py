"""Service catalog tables (migrations 0062, 0073, 0074; WP-030 s1, WP-031 s1)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, Unmapped, mapped_column, unmapped_column

from app.shared.db.models import Actors, Base, TenantEntity, Timestamps, Versioned

# Search (ADR-039; migration 0073): the database builds both from the row, in every language.
SEARCH_VECTOR = (
    "sx_search_vector("
    "catalog_texts(names) || ' ' || catalog_word_lists(keywords)"
    " || ' ' || catalog_texts(summaries),"
    " regexp_replace(catalog_texts(descriptions), '<[^>]*>|&[a-zA-Z0-9#]+;', ' ', 'g'))"
)
SEARCH_NAME = "sx_search_normalize(catalog_texts(names) || ' ' || catalog_word_lists(keywords))"


class ServiceCategory(TenantEntity):
    """A group of items in the catalog, named per language."""

    __tablename__ = "service_categories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_service_categories_tenant_id_id"),
        CheckConstraint("jsonb_typeof(names) = 'object'", name="names_object"),
        Index("ix_service_categories_tenant_sort", "tenant_id", "sort_order", "id"),
        Index("ix_service_categories_tenant_parent", "tenant_id", "parent_id", "sort_order"),
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["service_categories.tenant_id", "service_categories.id"],
            name="fk_service_categories_parent_id_service_categories",
            ondelete="RESTRICT",
        ),
    )

    # JSONB of language -> text; Any: SQLAlchemy's JSON typing.
    names: Mapped[dict[str, Any]] = mapped_column(JSONB)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    # WP-031 (plan D1): a tree of at most four levels; a disabled one hides its items.
    parent_id: Mapped[uuid.UUID | None]
    icon: Mapped[str | None] = mapped_column(String(40))
    descriptions: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")


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
        # WP-031 (migration 0073).
        CheckConstraint("status IN ('draft', 'published', 'retired')", name="status_code"),
        CheckConstraint("kind IN ('service', 'incident_template')", name="kind_code"),
        CheckConstraint(
            "jsonb_typeof(summaries) = 'object' AND jsonb_typeof(keywords) = 'object'",
            name="texts_object",
        ),
        CheckConstraint("cardinality(extra_category_ids) <= 5", name="extra_categories"),
        ForeignKeyConstraint(
            ["tenant_id", "template_id"],
            ["work_item_templates.tenant_id", "work_item_templates.id"],
            name="fk_catalog_items_template_id_work_item_templates",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["users.tenant_id", "users.id"],
            name="fk_catalog_items_owner_id_users",
            ondelete="RESTRICT",
        ),
        Index("ix_catalog_items_search", "search_vector", postgresql_using="gin"),
        Index(
            "ix_catalog_items_search_name",
            "search_name",
            postgresql_using="gin",
            postgresql_ops={"search_name": "gin_trgm_ops"},
        ),
        Index("ix_catalog_items_tenant_status", "tenant_id", "status", "category_id", "sort_order"),
        Index(
            "ix_catalog_items_extra_categories",
            "extra_category_ids",
            postgresql_using="gin",
        ),
        Index(
            "ix_catalog_items_tenant_due",
            "tenant_id",
            "publish_at",
            "retire_at",
            postgresql_where=text(
                "deleted_at IS NULL AND (publish_at IS NOT NULL OR retire_at IS NOT NULL)"
            ),
        ),
    )

    category_id: Mapped[uuid.UUID | None]
    # JSONB columns: names and descriptions per language, the form's questions, the approval
    # stage and the fulfilment plan, all checked by domain/items.py. Any: SQLAlchemy's JSON typing.
    names: Mapped[dict[str, Any]] = mapped_column(JSONB)
    descriptions: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    audience: Mapped[str] = mapped_column(String(20), server_default="everyone")
    # Replaced by `status` (0074); no longer read or written, dropped by a later contract step.
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
    # WP-031 s1 (domain/catalog.py): life, kind, texts, search words, placement.
    status: Mapped[str] = mapped_column(String(20), server_default="draft")
    publish_at: Mapped[datetime | None]
    retire_at: Mapped[datetime | None]
    published_at: Mapped[datetime | None]
    kind: Mapped[str] = mapped_column(String(30), server_default="service")
    template_id: Mapped[uuid.UUID | None]
    summaries: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    keywords: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    icon: Mapped[str | None] = mapped_column(String(40))
    owner_id: Mapped[uuid.UUID | None]
    featured: Mapped[bool] = mapped_column(Boolean, server_default="false")
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    subject_template: Mapped[str | None] = mapped_column(String(200))
    requesters_see_approval: Mapped[bool] = mapped_column(Boolean, server_default="true")
    starter: Mapped[bool] = mapped_column(Boolean, server_default="false")  # D-138
    extra_category_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid()), server_default="{}")
    # Columns of the table, not of the mapped object: never loaded or written by the ORM.
    search_vector: Unmapped[Any] = unmapped_column(
        TSVECTOR, Computed(SEARCH_VECTOR, persisted=True)
    )
    search_name: Unmapped[str] = unmapped_column(Text, Computed(SEARCH_NAME, persisted=True))


class CatalogSettings(Timestamps, Actors, Versioned, Base):
    """The tenant's catalog settings, one row (migration 0073, RLS)."""

    __tablename__ = "catalog_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), primary_key=True
    )
    # D-138: set when the starter catalog was added (or the tenant existed before it); never
    # cleared, so a tenant that deletes everything never gets it back by itself.
    starter_seeded_at: Mapped[datetime | None]
    hide_default_incident_template: Mapped[bool] = mapped_column(
        Boolean, server_default="false"
    )  # REQ-CAT-014


__all__ = ["CatalogItem", "CatalogSettings", "ServiceCategory"]
