"""Work item tables (WP-020; ADR-026). All tenant-scoped with RLS; see migration 0012.

One shared `work_items` table holds every ticket-like type (incidents now; service requests,
problems, changes and releases later), so lists, links and search span types without unions.
Types with fields of their own get a 1:1 extension table later. The configuration tables
(statuses, transitions, reasons, scales, matrix, categories, type settings) hold each tenant's
copy of the Appendix A defaults, seeded on first use and editable by admins (WP-020c).

References to users, sites, support groups and categories are same-tenant composite foreign
keys: the database refuses a link to another tenant's row even though FK checks bypass RLS.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.work_items.domain.classification import Impact, Priority, Scale, Urgency
from app.modules.work_items.domain.lifecycle import (
    ReasonList,
    ReasonMode,
    StatusCategory,
    WorkItemAction,
)
from app.modules.work_items.domain.types import Channel, WorkItemTypeCode
from app.shared.db.models import Base, TenantEntity, TenantKeyed


def _codes(column: str, values: Any) -> str:  # noqa: ANN401 - any StrEnum class
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


TYPE_CHECK = _codes("type", WorkItemTypeCode)


class WorkItemTypeSettings(TenantKeyed, Base):
    """Per tenant and type: display prefix, default priority, automatic status moves."""

    __tablename__ = "work_item_type_settings"
    __table_args__ = (
        CheckConstraint(TYPE_CHECK, name="type_code"),
        CheckConstraint("prefix ~ '^[A-Z]{2,6}$'", name="prefix_format"),
        CheckConstraint(_codes("default_priority", Priority), name="default_priority_code"),
        CheckConstraint(
            "default_impact IS NULL OR " + _codes("default_impact", Impact),
            name="default_impact_code",
        ),
        CheckConstraint(
            "default_urgency IS NULL OR " + _codes("default_urgency", Urgency),
            name="default_urgency_code",
        ),
    )

    type: Mapped[str] = mapped_column(String(20), primary_key=True)
    prefix: Mapped[str] = mapped_column(String(6))
    default_priority: Mapped[str] = mapped_column(String(10))
    # What the create form starts with (D-070); NULL: no default, the form starts empty.
    default_impact: Mapped[str | None] = mapped_column(String(30), server_default="team")
    default_urgency: Mapped[str | None] = mapped_column(String(30), server_default="medium")
    auto_status_on_assign: Mapped[bool] = mapped_column(Boolean, server_default="true")
    version: Mapped[int] = mapped_column(BigInteger, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_by: Mapped[uuid.UUID | None]


class WorkItemStatus(TenantKeyed, Base):
    """One status of a type's life cycle, with its fixed category."""

    __tablename__ = "work_item_statuses"
    __table_args__ = (
        CheckConstraint(TYPE_CHECK, name="type_code"),
        CheckConstraint(_codes("category", StatusCategory), name="category_code"),
        CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,39}$'", name="code_format"),
        CheckConstraint("colour ~ '^#[0-9a-fA-F]{6}$'", name="colour_format"),
    )

    type: Mapped[str] = mapped_column(String(20), primary_key=True)
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    category: Mapped[str] = mapped_column(String(10))
    colour: Mapped[str] = mapped_column(String(7))
    # Admin label overrides {"en": ..., "ar": ..., "ur": ...}; NULL = the shipped labels.
    labels: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    sort_order: Mapped[int] = mapped_column(Integer)
    system: Mapped[bool] = mapped_column(Boolean, server_default="false")
    disabled_at: Mapped[datetime | None]


class WorkItemTransition(TenantKeyed, Base):
    """`action` from `from_status` leads to `to_status` (NULL: back to the status before cancel)."""

    __tablename__ = "work_item_transitions"
    __table_args__ = (
        CheckConstraint(TYPE_CHECK, name="type_code"),
        CheckConstraint(_codes("action", WorkItemAction), name="action_code"),
        CheckConstraint(_codes("reason_mode", ReasonMode), name="reason_mode_code"),
        CheckConstraint(
            "reason_list IS NULL OR " + _codes("reason_list", ReasonList), name="reason_list_code"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "type", "from_status"],
            [
                "work_item_statuses.tenant_id",
                "work_item_statuses.type",
                "work_item_statuses.code",
            ],
            name="fk_work_item_transitions_from",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "type", "to_status"],
            [
                "work_item_statuses.tenant_id",
                "work_item_statuses.type",
                "work_item_statuses.code",
            ],
            name="fk_work_item_transitions_to",
        ),
    )

    type: Mapped[str] = mapped_column(String(20), primary_key=True)
    from_status: Mapped[str] = mapped_column(String(40), primary_key=True)
    action: Mapped[str] = mapped_column(String(30), primary_key=True)
    to_status: Mapped[str | None] = mapped_column(String(40))
    reason_mode: Mapped[str] = mapped_column(String(10))
    reason_list: Mapped[str | None] = mapped_column(String(20))


class WorkItemReason(TenantKeyed, Base):
    """One value of a reason pick list (pause, cancel, reopen, reassign ...)."""

    __tablename__ = "work_item_reasons"
    __table_args__ = (
        CheckConstraint(TYPE_CHECK, name="type_code"),
        CheckConstraint(_codes("list", ReasonList), name="list_code"),
        CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,39}$'", name="code_format"),
    )

    type: Mapped[str] = mapped_column(String(20), primary_key=True)
    list: Mapped[str] = mapped_column(String(20), primary_key=True)
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    labels: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    sort_order: Mapped[int] = mapped_column(Integer)
    disabled_at: Mapped[datetime | None]


class WorkItemScaleValue(TenantKeyed, Base):
    """One value of the impact, urgency or priority scale, with its rank (1 = lowest)."""

    __tablename__ = "work_item_scale_values"
    __table_args__ = (
        CheckConstraint(TYPE_CHECK, name="type_code"),
        CheckConstraint(_codes("scale", Scale), name="scale_code"),
        CheckConstraint(
            "(scale = 'impact' AND " + _codes("code", Impact) + ") OR "
            "(scale = 'urgency' AND " + _codes("code", Urgency) + ") OR "
            "(scale = 'priority' AND " + _codes("code", Priority) + ")",
            name="code_of_scale",
        ),
        CheckConstraint("colour IS NULL OR colour ~ '^#[0-9a-fA-F]{6}$'", name="colour_format"),
    )

    type: Mapped[str] = mapped_column(String(20), primary_key=True)
    scale: Mapped[str] = mapped_column(String(10), primary_key=True)
    code: Mapped[str] = mapped_column(String(30), primary_key=True)
    rank: Mapped[int] = mapped_column(Integer)
    colour: Mapped[str | None] = mapped_column(String(7))
    labels: Mapped[dict[str, str] | None] = mapped_column(JSONB)


class WorkItemPriorityCell(TenantKeyed, Base):
    """One cell of the priority matrix: impact x urgency → priority."""

    __tablename__ = "work_item_priority_matrix"
    __table_args__ = (
        CheckConstraint(TYPE_CHECK, name="type_code"),
        CheckConstraint(_codes("impact", Impact), name="impact_code"),
        CheckConstraint(_codes("urgency", Urgency), name="urgency_code"),
        CheckConstraint(_codes("priority", Priority), name="priority_code"),
    )

    type: Mapped[str] = mapped_column(String(20), primary_key=True)
    impact: Mapped[str] = mapped_column(String(30), primary_key=True)
    urgency: Mapped[str] = mapped_column(String(30), primary_key=True)
    priority: Mapped[str] = mapped_column(String(10))


class WorkItemCategory(TenantEntity):
    """One node of the three-level category tree (category, subcategory, item)."""

    __tablename__ = "work_item_categories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_work_item_categories_tenant_id_id"),
        CheckConstraint(TYPE_CHECK, name="type_code"),
        CheckConstraint("level BETWEEN 1 AND 3", name="level_range"),
        CheckConstraint("(level = 1) = (parent_id IS NULL)", name="root_has_no_parent"),
        # Seeded nodes carry a code (labelled by the UI); admin nodes carry their own labels.
        CheckConstraint("code IS NOT NULL OR labels IS NOT NULL", name="named"),
        CheckConstraint("code IS NULL OR code ~ '^[a-z][a-z0-9_]{1,39}$'", name="code_format"),
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["work_item_categories.tenant_id", "work_item_categories.id"],
            name="fk_work_item_categories_parent",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "default_group_id"],
            ["support_groups.tenant_id", "support_groups.id"],
            name="fk_work_item_categories_default_group",
        ),
        Index("ix_work_item_categories_tenant_type_parent", "tenant_id", "type", "parent_id"),
        Index(
            "uq_work_item_categories_tenant_type_parent_code",
            "tenant_id",
            "type",
            text("coalesce(parent_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            "code",
            unique=True,
            postgresql_where=text("code IS NOT NULL"),
        ),
    )

    type: Mapped[str] = mapped_column(String(20))
    parent_id: Mapped[uuid.UUID | None]
    level: Mapped[int] = mapped_column(Integer)
    code: Mapped[str | None] = mapped_column(String(40))
    labels: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    default_group_id: Mapped[uuid.UUID | None]
    disabled_at: Mapped[datetime | None]


class WorkItem(TenantEntity):
    """One ticket-like record of any type."""

    __tablename__ = "work_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_work_items_tenant_id_id"),
        UniqueConstraint("tenant_id", "display_id", name="uq_work_items_tenant_id_display_id"),
        UniqueConstraint(
            "tenant_id", "type", "display_number", name="uq_work_items_tenant_type_number"
        ),
        CheckConstraint(TYPE_CHECK, name="type_code"),
        CheckConstraint(_codes("channel", Channel), name="channel_code"),
        CheckConstraint(_codes("status_category", StatusCategory), name="status_category_code"),
        CheckConstraint("impact IS NULL OR " + _codes("impact", Impact), name="impact_code"),
        CheckConstraint("urgency IS NULL OR " + _codes("urgency", Urgency), name="urgency_code"),
        CheckConstraint(_codes("priority", Priority), name="priority_code"),
        CheckConstraint(
            "priority_source IN ('matrix', 'manual', 'default')", name="priority_source_code"
        ),
        CheckConstraint("length(btrim(subject)) BETWEEN 1 AND 250", name="subject_length"),
        CheckConstraint(
            "description IS NULL OR char_length(description) <= 100000", name="description_length"
        ),
        CheckConstraint("cardinality(tags) <= 20", name="tags_count"),
        CheckConstraint(
            "reopen_count >= 0 AND reassignment_count >= 0 AND paused_seconds >= 0",
            name="counters_positive",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "requester_id"], ["users.tenant_id", "users.id"], name="fk_wi_requester"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "on_behalf_of_id"],
            ["users.tenant_id", "users.id"],
            name="fk_wi_on_behalf_of",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "technician_id"],
            ["users.tenant_id", "users.id"],
            name="fk_wi_technician",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"], name="fk_wi_site"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "group_id"],
            ["support_groups.tenant_id", "support_groups.id"],
            name="fk_wi_group",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["work_item_categories.tenant_id", "work_item_categories.id"],
            name="fk_wi_category",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "type", "status"],
            [
                "work_item_statuses.tenant_id",
                "work_item_statuses.type",
                "work_item_statuses.code",
            ],
            name="fk_wi_status",
        ),
        # Lists: tenant and type first, then the usual narrowing column, then the sort, then id.
        Index(
            "ix_wi_tenant_type_cat_updated",
            "tenant_id",
            "type",
            "status_category",
            "updated_at",
            "id",
        ),
        Index("ix_wi_tenant_type_updated", "tenant_id", "type", "updated_at", "id"),
        Index("ix_wi_tenant_type_created", "tenant_id", "type", "created_at", "id"),
        Index(
            "ix_wi_tenant_type_group",
            "tenant_id",
            "type",
            "group_id",
            "status_category",
            "updated_at",
            "id",
        ),
        Index(
            "ix_wi_tenant_type_technician",
            "tenant_id",
            "type",
            "technician_id",
            "status_category",
            "updated_at",
            "id",
        ),
        Index(
            "ix_wi_tenant_type_requester", "tenant_id", "type", "requester_id", "created_at", "id"
        ),
        Index("ix_wi_tenant_type_site", "tenant_id", "type", "site_id", "status_category", "id"),
        Index("ix_wi_tenant_type_priority", "tenant_id", "type", "priority", "id"),
        Index("ix_wi_tenant_type_display_number", "tenant_id", "type", "display_number"),
        Index(
            "ix_wi_tenant_unassigned_site",
            "tenant_id",
            "type",
            "site_id",
            "updated_at",
            "id",
            postgresql_where=text("group_id IS NULL AND technician_id IS NULL"),
        ),
        Index("ix_wi_tags", "tags", postgresql_using="gin"),
    )

    type: Mapped[str] = mapped_column(String(20))
    display_id: Mapped[str] = mapped_column(String(30))
    display_number: Mapped[int] = mapped_column(BigInteger)
    subject: Mapped[str] = mapped_column(String(250))
    description: Mapped[str | None] = mapped_column(Text)  # sanitised HTML
    requester_id: Mapped[uuid.UUID]
    on_behalf_of_id: Mapped[uuid.UUID | None]
    channel: Mapped[str] = mapped_column(String(20))
    site_id: Mapped[uuid.UUID | None]
    group_id: Mapped[uuid.UUID | None]
    technician_id: Mapped[uuid.UUID | None]
    category_id: Mapped[uuid.UUID | None]
    impact: Mapped[str | None] = mapped_column(String(30))
    urgency: Mapped[str | None] = mapped_column(String(30))
    priority: Mapped[str] = mapped_column(String(10))
    priority_source: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(40))
    status_category: Mapped[str] = mapped_column(String(10))
    status_reason_code: Mapped[str | None] = mapped_column(String(40))
    status_reason_text: Mapped[str | None] = mapped_column(Text)
    status_before_cancel: Mapped[str | None] = mapped_column(String(40))
    status_changed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(40)), server_default="{}")
    first_assigned_at: Mapped[datetime | None]
    first_responded_at: Mapped[datetime | None]
    resolved_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]
    last_reopened_at: Mapped[datetime | None]
    reopen_count: Mapped[int] = mapped_column(Integer, server_default="0")
    reassignment_count: Mapped[int] = mapped_column(Integer, server_default="0")
    paused_since: Mapped[datetime | None]
    paused_seconds: Mapped[int] = mapped_column(BigInteger, server_default="0")
    # Filled by the SLA module (WP-025); NULL means "no SLA applies" (REQ-INC-011).
    sla_policy_id: Mapped[uuid.UUID | None]
    first_response_due_at: Mapped[datetime | None]
    resolution_due_at: Mapped[datetime | None]
