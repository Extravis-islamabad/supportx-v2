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
    Computed,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, Unmapped, mapped_column, unmapped_column

from app.modules.work_items.domain.classification import Impact, Priority, Scale, Urgency
from app.modules.work_items.domain.conversation import (
    DeliveryReason,
    DeliveryState,
    EntryKind,
    FirstResponseAction,
    FollowReason,
    ReplyMode,
    Visibility,
)
from app.modules.work_items.domain.lifecycle import (
    ReasonList,
    ReasonMode,
    StatusCategory,
    WorkItemAction,
)
from app.modules.work_items.domain.lists import BulkAction, BulkStatus, ViewVisibility
from app.modules.work_items.domain.parts import LinkKind, TaskPriority, TaskStatus, WorklogType
from app.modules.work_items.domain.templates import IMPACT_DETAILS_MAX, PickList
from app.modules.work_items.domain.types import Channel, WorkItemTypeCode
from app.shared.db.models import Base, TenantEntity, TenantKeyed, utc_now


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
        CheckConstraint(
            "first_response_on <@ ARRAY["
            + ", ".join(f"'{v}'" for v in FirstResponseAction)
            + "]::varchar[]",
            name="first_response_on_codes",
        ),
        CheckConstraint(
            "auto_close_days IS NULL OR auto_close_days BETWEEN 1 AND 30",
            name="auto_close_days_range",
        ),
        CheckConstraint("reopen_window_days BETWEEN 1 AND 30", name="reopen_window_days_range"),
    )

    type: Mapped[str] = mapped_column(String(20), primary_key=True)
    prefix: Mapped[str] = mapped_column(String(6))
    default_priority: Mapped[str] = mapped_column(String(10))
    # What the create form starts with (D-075); NULL: no default, the form starts empty.
    default_impact: Mapped[str | None] = mapped_column(String(30), server_default="team")
    default_urgency: Mapped[str | None] = mapped_column(String(30), server_default="medium")
    auto_status_on_assign: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # D-068: whoever hands a record out of their own reach keeps following it unless they untick.
    keep_following_on_handover: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # Which actions stamp the first response (REQ-INC-065); a private note only if listed.
    first_response_on: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), server_default="{reply,public_note}"
    )
    # Closure rules (REQ-INC-094): fields required before resolving and before closing.
    resolve_requires: Mapped[list[str]] = mapped_column(
        ARRAY(String(60)), server_default="{resolution}"
    )
    close_requires: Mapped[list[str]] = mapped_column(
        ARRAY(String(60)), server_default="{closure_code}"
    )
    # Open work at resolve or close (REQ-INC-095): kind -> "warn" or "block"; missing kinds take
    # the defaults (domain/closure.py). "Complete it on close" is off by default.
    open_work: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    complete_open_work: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # Business days a resolved record waits for the requester (REQ-INC-096); NULL: off, the
    # default until a channel can tell requesters (product owner, 2026-10-28).
    auto_close_days: Mapped[int | None] = mapped_column(Integer)
    # Days after resolution or closure in which a requester reply reopens (REQ-INC-098).
    reopen_window_days: Mapped[int] = mapped_column(Integer, server_default="7")
    # REQ-INC-072 AC3 (D-112): a task's owner may work on it without access to the record.
    task_owner_access: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # Which shipped defaults this tenant has (catalogue.SEED_VERSION); older ones are topped up.
    seed_version: Mapped[int] = mapped_column(Integer, server_default="1")
    version: Mapped[int] = mapped_column(BigInteger, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=utc_now)
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
    # A requester reply moves a record in this (paused) status back to in progress (REQ-INC-051).
    resume_on_requester_reply: Mapped[bool] = mapped_column(Boolean, server_default="false")


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
    """One value of a pick list: the reason lists (pause, cancel ...), levels, closure codes.

    Values are retired (`disabled_at`), never deleted, so old records keep their label
    (REQ-ADM-043). Seeded values carry no labels (the UI labels their code); admin values carry
    their own translations.
    """

    __tablename__ = "work_item_reasons"
    __table_args__ = (
        CheckConstraint(TYPE_CHECK, name="type_code"),
        CheckConstraint(_codes("list", PickList), name="list_code"),
        CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,39}$'", name="code_format"),
        CheckConstraint("colour IS NULL OR colour ~ '^#[0-9a-fA-F]{6}$'", name="colour_format"),
    )

    type: Mapped[str] = mapped_column(String(20), primary_key=True)
    list: Mapped[str] = mapped_column(String(20), primary_key=True)
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    labels: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    sort_order: Mapped[int] = mapped_column(Integer)
    colour: Mapped[str | None] = mapped_column(String(7))
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


class WorkItemTemplate(TenantEntity):
    """An incident (or other type's) template: shown and required fields, starting values.

    REQ-INC-035. `field_rules` maps each configurable field to shown / required / requester can
    see / requester can fill in; `defaults` maps fields to starting values. Disabled templates
    are not offered for new records but still name the records created from them.
    """

    __tablename__ = "work_item_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_work_item_templates_tenant_id_id"),
        CheckConstraint(TYPE_CHECK, name="type_code"),
        CheckConstraint("code IS NOT NULL OR labels IS NOT NULL", name="named"),
        CheckConstraint("code IS NULL OR code ~ '^[a-z][a-z0-9_]{1,39}$'", name="code_format"),
        CheckConstraint("NOT (is_default AND disabled_at IS NOT NULL)", name="default_enabled"),
        ForeignKeyConstraint(
            ["tenant_id", "copied_from_id"],
            ["work_item_templates.tenant_id", "work_item_templates.id"],
            name="fk_work_item_templates_copied_from",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "desk_id"], ["desks.tenant_id", "desks.id"], name="fk_wit_desk"
        ),
        Index("ix_work_item_templates_tenant_type", "tenant_id", "type", "disabled_at"),
        Index(
            "uq_work_item_templates_tenant_type_default",
            "tenant_id",
            "type",
            unique=True,
            postgresql_where=text("is_default AND deleted_at IS NULL"),
        ),
    )

    type: Mapped[str] = mapped_column(String(20))
    code: Mapped[str | None] = mapped_column(String(40))
    labels: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(String(500))
    group_name: Mapped[str | None] = mapped_column(String(60))
    is_default: Mapped[bool] = mapped_column(Boolean, server_default="false")
    for_requesters: Mapped[bool] = mapped_column(Boolean, server_default="false")
    field_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    defaults: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    copied_from_id: Mapped[uuid.UUID | None]
    disabled_at: Mapped[datetime | None]
    # The desk the template belongs to (REQ-ESM-002, D-061).
    desk_id: Mapped[uuid.UUID]


# Description is sanitised HTML: tags and entities become spaces before indexing (migration 0020);
# the custom field text follows (written by the app with the values, migration 0021, ADR-030).
SEARCH_VECTOR = (
    "sx_search_vector(subject, regexp_replace(coalesce(description, ''),"
    " '<[^>]*>|&[a-zA-Z0-9#]+;', ' ', 'g') || ' ' || coalesce(custom_text, ''))"
)


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
            "priority_source IN ('matrix', 'manual', 'default', 'rule')",
            name="priority_source_code",
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
            ["tenant_id", "department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_wi_department",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "desk_id"], ["desks.tenant_id", "desks.id"], name="fk_wi_desk"
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
            ["tenant_id", "template_id"],
            ["work_item_templates.tenant_id", "work_item_templates.id"],
            name="fk_wi_template",
        ),
        CheckConstraint(
            f"impact_details IS NULL OR char_length(impact_details) <= {IMPACT_DETAILS_MAX}",
            name="impact_details_length",
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
        # Reports (lane C, WP-035): resolution trends and MTTR; by category.
        Index(
            "ix_wi_tenant_type_resolved",
            "tenant_id",
            "type",
            "resolved_at",
            postgresql_where=text("resolved_at IS NOT NULL"),
        ),
        Index("ix_wi_tenant_type_category", "tenant_id", "type", "category_id", "status_category"),
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
        # Search (WP-027, ADR-029): full text, and trigrams of the subject for typos.
        Index("ix_wi_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_wi_search_subject",
            "search_subject",
            postgresql_using="gin",
            postgresql_ops={"search_subject": "gin_trgm_ops"},
        ),
        Index(
            "ix_wi_custom",
            "custom",
            postgresql_using="gin",
            postgresql_ops={"custom": "jsonb_path_ops"},
        ),
        # Auto-close (REQ-INC-096): resolved records whose requester was told.
        Index(
            "ix_wi_resolution_notified",
            "tenant_id",
            "resolution_notified_at",
            postgresql_where=text(
                "status_category = 'resolved' AND resolution_notified_at IS NOT NULL"
            ),
        ),
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
    # From the requester by default, changeable (REQ-INC-016, WP-021).
    department_id: Mapped[uuid.UUID | None]
    # Every record belongs to a desk from MVP (REQ-ESM-002, D-061): the IT desk until ESM.
    desk_id: Mapped[uuid.UUID]
    group_id: Mapped[uuid.UUID | None]
    technician_id: Mapped[uuid.UUID | None]
    category_id: Mapped[uuid.UUID | None]
    impact: Mapped[str | None] = mapped_column(String(30))
    # Plain text: who and what is affected, in the reporter's words (REQ-INC-001).
    impact_details: Mapped[str | None] = mapped_column(Text)
    urgency: Mapped[str | None] = mapped_column(String(30))
    priority: Mapped[str] = mapped_column(String(10))
    # Support level, a code of the `level` pick list (REQ-INC-007); retired codes stay readable.
    level: Mapped[str | None] = mapped_column(String(40))
    template_id: Mapped[uuid.UUID | None]
    # Custom field values by key (WP-026, metadata module); typed JSON, GIN-indexed.
    custom: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    # Their free text (text, long text, email, phone, web address), kept on every save for
    # search: a generated column cannot tell free text from choice codes (D-087).
    custom_text: Mapped[str | None] = mapped_column(Text)
    priority_source: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(40))
    status_category: Mapped[str] = mapped_column(String(10))
    status_reason_code: Mapped[str | None] = mapped_column(String(40))
    status_reason_text: Mapped[str | None] = mapped_column(Text)
    status_before_cancel: Mapped[str | None] = mapped_column(String(40))
    # The fix (REQ-INC-090), sanitised rich text; cleared on reopen (history keeps it).
    resolution: Mapped[str | None] = mapped_column(Text)
    # A code of the closure_code pick list (REQ-INC-093); cleared on reopen (history keeps it).
    closure_code: Mapped[str | None] = mapped_column(String(40))
    # When the requester was told of the resolution: auto-close counts from here, never without.
    resolution_notified_at: Mapped[datetime | None]
    # A requester reply after the reopen window starts a new record following this one (098).
    follows_id: Mapped[uuid.UUID | None]
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
    # Search (migrations 0020, 0021): generated by the database from subject, description and the
    # custom field text. Columns of the table, not of the mapped object: the ORM never loads or
    # returns them; search queries use `WorkItem.__table__.c` (work_items/service/search.py).
    search_vector: Unmapped[Any] = unmapped_column(
        TSVECTOR, Computed(SEARCH_VECTOR, persisted=True)
    )
    search_subject: Unmapped[str] = unmapped_column(
        Text, Computed("sx_search_normalize(subject)", persisted=True)
    )


def _work_item_fk(name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", "work_item_id"], ["work_items.tenant_id", "work_items.id"], name=name
    )


class WorkItemConversation(TenantEntity):
    """One reply or note on a work item (REQ-INC-057/058/061). The body is sanitised HTML."""

    __tablename__ = "work_item_conversations"
    __table_args__ = (
        _work_item_fk("fk_wic_work_item"),
        CheckConstraint(_codes("kind", EntryKind), name="kind_code"),
        CheckConstraint(_codes("visibility", Visibility), name="visibility_code"),
        # Replies go to the requester and others: always public.
        CheckConstraint("kind = 'note' OR visibility = 'public'", name="reply_is_public"),
        CheckConstraint(
            "reply_mode IS NULL OR " + _codes("reply_mode", ReplyMode), name="reply_mode_code"
        ),
        CheckConstraint("(kind = 'reply') = (reply_mode IS NOT NULL)", name="reply_has_mode"),
        CheckConstraint(
            "delivery_state IS NULL OR " + _codes("delivery_state", DeliveryState),
            name="delivery_state_code",
        ),
        CheckConstraint(
            "delivery_reason IS NULL OR " + _codes("delivery_reason", DeliveryReason),
            name="delivery_reason_code",
        ),
        CheckConstraint("(kind = 'reply') = (delivery_state IS NOT NULL)", name="reply_delivery"),
        CheckConstraint("char_length(body) BETWEEN 1 AND 100000", name="body_length"),
        Index("ix_wic_tenant_item_created", "tenant_id", "work_item_id", "created_at", "id"),
    )

    work_item_id: Mapped[uuid.UUID]
    kind: Mapped[str] = mapped_column(String(10))
    visibility: Mapped[str] = mapped_column(String(10))
    reply_mode: Mapped[str | None] = mapped_column(String(10))
    body: Mapped[str] = mapped_column(Text)
    # Replies: {"to": [email, ...], "cc": [email, ...]} as the composer sent them.
    recipients: Mapped[dict[str, list[str]] | None] = mapped_column(JSONB)
    delivery_state: Mapped[str | None] = mapped_column(String(20))
    delivery_reason: Mapped[str | None] = mapped_column(String(40))
    first_response: Mapped[bool] = mapped_column(Boolean, server_default="false")
    mentioned_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default="{}"
    )


class WorkItemFollower(TenantEntity):
    """Someone following a work item (REQ-INC-056/151). Unfollowing soft-deletes the row.

    `grants_access` (D-068): the follower may open the record, see it live and add private notes
    even outside their own scope; only a hand-over (and later, sharing) grants it. Following for
    any other reason never widens what someone may see (REQ-INC-063).
    """

    __tablename__ = "work_item_followers"
    __table_args__ = (
        _work_item_fk("fk_wif_work_item"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_wif_user"
        ),
        CheckConstraint(_codes("reason", FollowReason), name="reason_code"),
        Index(
            "uq_wif_tenant_item_user",
            "tenant_id",
            "work_item_id",
            "user_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_wif_tenant_user_access",
            "tenant_id",
            "user_id",
            "work_item_id",
            postgresql_where=text("deleted_at IS NULL AND grants_access"),
        ),
    )

    work_item_id: Mapped[uuid.UUID]
    user_id: Mapped[uuid.UUID]
    reason: Mapped[str] = mapped_column(String(20))
    grants_access: Mapped[bool] = mapped_column(Boolean, server_default="false")


class WorkItemReplyTemplate(TenantEntity):
    """A reply template technicians insert into the composer (REQ-INC-058)."""

    __tablename__ = "work_item_reply_templates"
    __table_args__ = (
        CheckConstraint(TYPE_CHECK, name="type_code"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 120", name="name_length"),
        CheckConstraint("char_length(body) BETWEEN 1 AND 100000", name="body_length"),
        Index(
            "uq_wirt_tenant_type_name",
            "tenant_id",
            "type",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)


class WorkItemView(TenantEntity):
    """A saved view (REQ-INC-106): a filter in the shared DSL, columns and sort, by its owner.

    `filter` and `sort` are the list API's own parameters, stored as sent (AC3). A shared view
    is listed for everyone who may see the list; only its owner changes or removes it.
    """

    __tablename__ = "work_item_views"
    __table_args__ = (
        CheckConstraint(TYPE_CHECK, name="type_code"),
        CheckConstraint(_codes("visibility", ViewVisibility), name="visibility_code"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 120", name="name_length"),
        CheckConstraint("jsonb_array_length(columns) <= 40", name="columns_limit"),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], name="fk_wiv_owner"
        ),
        Index(
            "uq_wiv_tenant_type_owner_name",
            "tenant_id",
            "type",
            "owner_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_wiv_tenant_type_shared",
            "tenant_id",
            "type",
            postgresql_where=text("deleted_at IS NULL AND visibility = 'shared'"),
        ),
    )

    type: Mapped[str] = mapped_column(String(20))
    owner_id: Mapped[uuid.UUID]
    name: Mapped[str] = mapped_column(String(120))
    visibility: Mapped[str] = mapped_column(String(10))
    # The list API's `filter` (FilterExpression JSON) or null for "everything I may see".
    filter: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # [{"key": "subject", "width": 240}, ...]; empty = the default columns.
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    sort: Mapped[str | None] = mapped_column(String(200))


class WorkItemListSetting(TenantEntity):
    """One user's columns, sort and page size for one view (REQ-INC-104 AC1/AC3, 110).

    `view_key` is a built-in view code or `custom:<view id>`; settings never cross views.
    """

    __tablename__ = "work_item_list_settings"
    __table_args__ = (
        CheckConstraint(TYPE_CHECK, name="type_code"),
        CheckConstraint("page_size IN (25, 50, 100)", name="page_size_choice"),
        CheckConstraint("jsonb_array_length(columns) <= 40", name="columns_limit"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_wils_user"
        ),
        Index(
            "uq_wils_tenant_user_type_view",
            "tenant_id",
            "user_id",
            "type",
            "view_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    type: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[uuid.UUID]
    view_key: Mapped[str] = mapped_column(String(60))
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    sort: Mapped[str | None] = mapped_column(String(200))
    page_size: Mapped[int] = mapped_column(Integer, server_default="50")


class WorkItemBulkJob(TenantEntity):
    """A bulk change of up to 1,000 records (REQ-INC-119/120), run by the consumers worker.

    The records are frozen when the job starts (`record_ids`); each runs as the requester
    (`created_by`) with its own permissions, transitions and closure rules. `results` holds one
    entry per finished record: {"id", "display_id", "outcome", "code", "params"}.
    """

    __tablename__ = "work_item_bulk_jobs"
    __table_args__ = (
        CheckConstraint(TYPE_CHECK, name="type_code"),
        CheckConstraint(_codes("action", BulkAction), name="action_code"),
        CheckConstraint(_codes("status", BulkStatus), name="status_code"),
        CheckConstraint("cardinality(record_ids) BETWEEN 1 AND 1000", name="record_limit"),
        CheckConstraint("processed BETWEEN 0 AND total", name="processed_range"),
        Index("ix_wibj_tenant_creator_created", "tenant_id", "created_by", "created_at"),
        Index(
            "ix_wibj_tenant_pending",
            "tenant_id",
            "created_at",
            postgresql_where=text("status IN ('queued', 'running') AND deleted_at IS NULL"),
        ),
    )

    type: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(20))
    # Edit: only the changed fields; assign: technician and group; resolve/close: their fields.
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    source: Mapped[str] = mapped_column(String(20))  # history source of the request (ui, api)
    record_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    status: Mapped[str] = mapped_column(String(20))
    total: Mapped[int] = mapped_column(Integer)
    processed: Mapped[int] = mapped_column(Integer, server_default="0")
    done_count: Mapped[int] = mapped_column(Integer, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, server_default="0")
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class WorkItemTask(TenantEntity):
    """A task on a work item (REQ-INC-072): its own status, owner, group, priority and due time.

    `position` orders a record's tasks; moving one renumbers the record's tasks in one save.
    """

    __tablename__ = "work_item_tasks"
    __table_args__ = (
        _work_item_fk("fk_wit_work_item"),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], name="fk_wit_owner"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "group_id"],
            ["support_groups.tenant_id", "support_groups.id"],
            name="fk_wit_group",
        ),
        CheckConstraint(_codes("status", TaskStatus), name="status_code"),
        CheckConstraint(_codes("priority", TaskPriority), name="priority_code"),
        CheckConstraint("length(btrim(title)) BETWEEN 1 AND 200", name="title_length"),
        CheckConstraint(
            "description IS NULL OR char_length(description) <= 4000", name="description_length"
        ),
        Index("ix_wit_tenant_item_position", "tenant_id", "work_item_id", "position", "id"),
        Index(
            "ix_wit_tenant_owner_open",
            "tenant_id",
            "owner_id",
            postgresql_where=text("deleted_at IS NULL AND status IN ('open', 'in_progress')"),
        ),
    )

    work_item_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None]
    group_id: Mapped[uuid.UUID | None]
    status: Mapped[str] = mapped_column(String(20), server_default="open")
    priority: Mapped[str] = mapped_column(String(10), server_default="normal")
    due_at: Mapped[datetime | None]
    position: Mapped[int] = mapped_column(Integer)
    done_at: Mapped[datetime | None]


class WorkItemWorklog(TenantEntity):
    """Time spent on a work item (REQ-INC-067): whose, what kind, when and how long.

    Times only (costs are V1, D-047). Start, end and minutes always agree (domain/parts.py).
    """

    __tablename__ = "work_item_worklogs"
    __table_args__ = (
        _work_item_fk("fk_wiw_work_item"),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"], ["users.tenant_id", "users.id"], name="fk_wiw_owner"
        ),
        CheckConstraint(_codes("worklog_type", WorklogType), name="worklog_type_code"),
        CheckConstraint("ended_at >= started_at", name="end_after_start"),
        CheckConstraint("minutes BETWEEN 1 AND 10080", name="minutes_range"),
        CheckConstraint(
            "description IS NULL OR char_length(description) <= 4000", name="description_length"
        ),
        Index("ix_wiw_tenant_item_start", "tenant_id", "work_item_id", "started_at", "id"),
        Index("ix_wiw_tenant_owner_start", "tenant_id", "owner_id", "started_at"),
    )

    work_item_id: Mapped[uuid.UUID]
    owner_id: Mapped[uuid.UUID]
    worklog_type: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime]
    minutes: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)


class WorkItemLink(TenantEntity):
    """Two work items linked (REQ-INC-084), shown and recorded on both.

    One row per pair and kind: `source_id` follows `target_id` for `follows`; for `related` the
    pair is stored in ID order, so A-B and B-A are the same link.
    """

    __tablename__ = "work_item_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "source_id"],
            ["work_items.tenant_id", "work_items.id"],
            name="fk_wil_source",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "target_id"],
            ["work_items.tenant_id", "work_items.id"],
            name="fk_wil_target",
        ),
        CheckConstraint(_codes("kind", LinkKind), name="kind_code"),
        CheckConstraint("source_id <> target_id", name="not_itself"),
        CheckConstraint("kind <> 'related' OR source_id < target_id", name="related_in_order"),
        CheckConstraint("comment IS NULL OR char_length(comment) <= 500", name="comment_length"),
        Index(
            "uq_wil_tenant_pair_kind",
            "tenant_id",
            "source_id",
            "target_id",
            "kind",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_wil_tenant_target",
            "tenant_id",
            "target_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    source_id: Mapped[uuid.UUID]
    target_id: Mapped[uuid.UUID]
    kind: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(String(500))
