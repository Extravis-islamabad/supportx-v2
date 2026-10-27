"""Work item HTTP API: one router per type, `/api/v1/<type path>` (WP-020; ADR-026). No logic here.

`build_router(INCIDENT)` gives `/api/v1/incidents/...`; later types get their own paths, schemas
and permissions from the same factory (D3). Writes use If-Match (409 says who changed what);
create takes an Idempotency-Key. Status changes only through `/actions/{action}`; group and
technician only through `/assign` and `/take`.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import BadRequest, ProblemDetail
from app.modules import metadata
from app.modules.audit import AuditNote, audited, entries_for_changes
from app.modules.identity_access import PolicyService, Subject, get_policy, user_contacts
from app.modules.work_items.api.conversation_routes import (
    add_collection_routes,
    add_record_routes,
)
from app.modules.work_items.api.people import PersonOut, people_out
from app.modules.work_items.api.settings_routes import add_settings_routes
from app.modules.work_items.domain.classification import (
    PRIORITY_REASON_MAX,
    Impact,
    Priority,
    PrioritySource,
    Scale,
    Urgency,
)
from app.modules.work_items.domain.conversation import FirstResponseAction
from app.modules.work_items.domain.lifecycle import (
    REASON_TEXT_MAX,
    USER_ACTIONS,
    ReasonList,
    ReasonMode,
    StatusCategory,
    WorkItemAction,
)
from app.modules.work_items.domain.templates import IMPACT_DETAILS_MAX, REASON_LISTS, PickList
from app.modules.work_items.domain.types import (
    DESCRIPTION_MAX,
    SUBJECT_MAX,
    TAGS_MAX,
    Channel,
    WorkItemType,
)
from app.modules.work_items.infra.models import WorkItem, WorkItemCategory
from app.modules.work_items.service import search as search_service
from app.modules.work_items.service import settings as settings_service
from app.modules.work_items.service import work_items as service
from app.modules.work_items.service.access import FIELDS
from app.modules.work_items.service.catalogue import Catalogue, ReasonInfo
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import ListQuery, Page, PageResult, list_query, request_zone
from app.shared.api.ratelimit import rate_limit
from app.shared.history import Actors, ChangeKind, HistoryEntry, Source, source_of

Responses = dict[int | str, dict[str, object]]
RESPONSES: Responses = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission or licence feature."},
    404: {"model": ProblemDetail, "description": "No such record visible to you."},
}
CONFLICT: Responses = {
    409: {
        "model": ProblemDetail,
        "description": "version_conflict (who changed what), invalid_transition, record_closed, "
        "would_lose_access, already_taken or already_yours.",
    }
}


# --- schemas --------------------------------------------------------------------------------------


class WorkItemIn(BaseModel):
    """A new record. Group and technician need the assign permission."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(max_length=SUBJECT_MAX * 2)
    description: str | None = Field(
        default=None, max_length=DESCRIPTION_MAX * 2, description="Rich text (HTML), sanitised."
    )
    requester_id: uuid.UUID
    on_behalf_of_id: uuid.UUID | None = None
    channel: Channel | None = Field(
        default=None, description="Only phone or walk_up may be chosen; others are set for you."
    )
    site_id: uuid.UUID | None = Field(default=None, description="Default: the requester's site.")
    department_id: uuid.UUID | None = Field(
        default=None, description="Default: the requester's department (WP-021)."
    )
    group_id: uuid.UUID | None = None
    technician_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    impact: Impact | None = None
    impact_details: str | None = Field(
        default=None, max_length=IMPACT_DETAILS_MAX * 2, description="Plain text."
    )
    urgency: Urgency | None = None
    level: str | None = Field(default=None, max_length=40, description="A `level` list code.")
    template_id: uuid.UUID | None = Field(
        default=None, description="Default: the tenant's default template (its rules apply)."
    )
    custom: dict[str, Any] | None = Field(
        default=None, description="Custom field values by key (GET /custom-fields?entity=...)."
    )
    priority: Priority | None = Field(
        default=None, description="Set by hand (needs change_priority and a reason)."
    )
    priority_reason: str | None = Field(default=None, max_length=PRIORITY_REASON_MAX)
    tags: list[str] = Field(default_factory=list, max_length=TAGS_MAX * 2)
    confirm_lose_access: bool = Field(
        default=False, description="Confirm handing it to people you cannot see records of."
    )
    keep_following: bool | None = Field(
        default=None,
        description="With confirm_lose_access: keep following it (null: tenant default, D-068).",
    )


class WorkItemPatch(BaseModel):
    """Fields to change (only those sent). Not status, group or technician."""

    model_config = ConfigDict(extra="forbid")

    subject: str | None = Field(default=None, max_length=SUBJECT_MAX * 2)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX * 2)
    requester_id: uuid.UUID | None = None
    on_behalf_of_id: uuid.UUID | None = None
    channel: Channel | None = None
    site_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    impact: Impact | None = None
    impact_details: str | None = Field(default=None, max_length=IMPACT_DETAILS_MAX * 2)
    urgency: Urgency | None = None
    level: str | None = Field(default=None, max_length=40)
    custom: dict[str, Any] | None = Field(
        default=None, description="Custom values to change by key (null clears one); others kept."
    )
    priority: Priority | None = Field(
        default=None,
        description="A value sets it by hand (with a reason); null: back to the matrix.",
    )
    priority_reason: str | None = Field(default=None, max_length=PRIORITY_REASON_MAX)
    tags: list[str] | None = Field(default=None, max_length=TAGS_MAX * 2)
    confirm_lose_access: bool = False
    keep_following: bool | None = Field(
        default=None,
        description="With confirm_lose_access: keep following it (null: tenant default, D-068).",
    )


class WorkItemTransitionIn(BaseModel):
    """The reason, when the transition asks for one."""

    model_config = ConfigDict(extra="forbid")

    reason_code: str | None = Field(default=None, max_length=40)
    reason_text: str | None = Field(default=None, max_length=REASON_TEXT_MAX)
    group_id: uuid.UUID | None = Field(
        default=None,
        description="Start work on an unassigned record: which of your groups (as with Take).",
    )


class WorkItemAssignIn(BaseModel):
    """New group and technician (either may be null). Moving between groups needs a reason."""

    model_config = ConfigDict(extra="forbid")

    group_id: uuid.UUID | None = None
    technician_id: uuid.UUID | None = None
    reason_code: str | None = Field(default=None, max_length=40)
    reason_text: str | None = Field(default=None, max_length=PRIORITY_REASON_MAX)
    confirm_lose_access: bool = Field(
        default=False, description="You confirmed it leaves your reach (D-053)."
    )
    keep_following: bool | None = Field(
        default=None,
        description="With confirm_lose_access: keep following it (null: tenant default, D-068).",
    )


class WorkItemTakeIn(BaseModel):
    """Which of your groups, when it has none and you are in several."""

    model_config = ConfigDict(extra="forbid")

    group_id: uuid.UUID | None = None


_people = people_out


class WorkItemActionStateOut(BaseModel):
    """An action as you may use it now. Disabled ones carry a reason code (labelled)."""

    action: str
    allowed: bool
    reason: str | None = None
    reason_mode: ReasonMode = ReasonMode.NONE
    reason_list: ReasonList | None = None


class WorkItemOut(BaseModel):
    """A work item as staff see it."""

    id: uuid.UUID
    type: str
    display_id: str
    subject: str
    description: str | None
    requester_id: uuid.UUID
    on_behalf_of_id: uuid.UUID | None
    channel: Channel
    site_id: uuid.UUID | None
    department_id: uuid.UUID | None
    desk_id: uuid.UUID
    group_id: uuid.UUID | None
    technician_id: uuid.UUID | None
    category_id: uuid.UUID | None
    impact: Impact | None
    impact_details: str | None
    urgency: Urgency | None
    priority: Priority
    priority_source: PrioritySource
    level: str | None = Field(description="A `level` list code (may be a retired one).")
    template_id: uuid.UUID | None = Field(description="The template it was created from.")
    custom: dict[str, Any] = Field(description="Custom field values by key (WP-026).")
    status: str
    status_category: StatusCategory
    status_reason_code: str | None
    status_reason_text: str | None
    status_changed_at: datetime
    tags: list[str]
    first_assigned_at: datetime | None
    first_responded_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    last_reopened_at: datetime | None
    reopen_count: int
    reassignment_count: int
    paused_seconds: int
    paused_since: datetime | None
    sla_policy_id: uuid.UUID | None = Field(description="Null: no SLA applies (REQ-INC-011).")
    first_response_due_at: datetime | None
    resolution_due_at: datetime | None
    created_at: datetime
    created_by: uuid.UUID | None
    updated_at: datetime
    updated_by: uuid.UUID | None
    version: int = Field(description="Send it back as If-Match (the ETag) to change it.")
    actions: list[WorkItemActionStateOut] = Field(
        description="Status actions, always in the same order."
    )
    operations: list[WorkItemActionStateOut] = Field(
        description="edit, assign, take, change_priority, delete: whether you may, and why not."
    )
    history_count: int
    people: dict[str, PersonOut] = Field(description="The people on the record, by user ID.")
    visible: bool = Field(
        default=True, description="False right after you handed it away (D-053): no more access."
    )
    conversation_actions: list[WorkItemActionStateOut] = Field(
        description="add_note, reply, manage_followers: whether you may, and why not."
    )
    following: bool = Field(description="You follow this record.")
    conversation_count: int = Field(description="Replies and notes.")

    @classmethod
    def of(cls, view: service.WorkItemView) -> "WorkItemOut":
        """From the service view."""
        r = view.record
        return cls(
            **{name: getattr(r, name) for name in _RECORD_FIELDS},
            actions=[_state(a) for a in view.actions],
            operations=[_state(a) for a in view.operations],
            history_count=view.history_count,
            people=_people(view.names),
            visible=view.visible,
            conversation_actions=[_state(a) for a in view.conversation],
            following=view.following,
            conversation_count=view.conversation_count,
        )


_RECORD_FIELDS = (
    "id",
    "type",
    "display_id",
    "subject",
    "description",
    "requester_id",
    "on_behalf_of_id",
    "channel",
    "site_id",
    "department_id",
    "desk_id",
    "group_id",
    "technician_id",
    "category_id",
    "impact",
    "impact_details",
    "urgency",
    "priority",
    "priority_source",
    "level",
    "template_id",
    "custom",
    "status",
    "status_category",
    "status_reason_code",
    "status_reason_text",
    "status_changed_at",
    "tags",
    "first_assigned_at",
    "first_responded_at",
    "resolved_at",
    "closed_at",
    "last_reopened_at",
    "reopen_count",
    "reassignment_count",
    "paused_seconds",
    "paused_since",
    "sla_policy_id",
    "first_response_due_at",
    "resolution_due_at",
    "created_at",
    "created_by",
    "updated_at",
    "updated_by",
    "version",
)


def _state(a: service.ActionState) -> WorkItemActionStateOut:
    return WorkItemActionStateOut(
        action=a.action,
        allowed=a.allowed,
        reason=a.reason,
        reason_mode=ReasonMode(a.reason_mode),
        reason_list=ReasonList(a.reason_list) if a.reason_list else None,
    )


class WorkItemListItem(BaseModel):
    """One row of a list."""

    id: uuid.UUID
    display_id: str
    subject: str
    requester_id: uuid.UUID
    technician_id: uuid.UUID | None
    group_id: uuid.UUID | None
    site_id: uuid.UUID | None
    category_id: uuid.UUID | None
    priority: Priority
    priority_source: PrioritySource
    level: str | None
    status: str
    status_category: StatusCategory
    status_reason_code: str | None
    channel: Channel
    tags: list[str]
    sla_policy_id: uuid.UUID | None
    resolution_due_at: datetime | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    version: int


class WorkItemPage(Page[WorkItemListItem]):
    """One page of a list, with the display names of the people on it."""

    people: dict[str, PersonOut] = Field(default_factory=dict)


class WorkItemSearchOut(BaseModel):
    """Search results, best first, with the people on them (name and email)."""

    items: list[WorkItemListItem]
    people: dict[str, PersonOut] = Field(default_factory=dict)


class WorkItemViewCountOut(BaseModel):
    """A built-in view and how many records you see in it (capped)."""

    view: str
    count: int
    capped: bool = Field(description="True: more than `count`.")


class WorkItemAssigneeOut(BaseModel):
    """Someone who can be assigned, with their open load."""

    id: uuid.UUID
    display_name: str
    email: str = Field(description="Second line in pickers: two people may share a name.")
    open_count: int


class WorkItemStatusOut(BaseModel):
    """One status of the tenant's life cycle."""

    code: str
    category: StatusCategory
    colour: str
    labels: dict[str, str] | None = Field(description="Admin overrides; null: shipped labels.")
    system: bool
    disabled: bool


class WorkItemTransitionOut(BaseModel):
    """One allowed move."""

    from_status: str
    action: WorkItemAction
    to_status: str | None = Field(description="Null: back to the status before canceling.")
    reason_mode: ReasonMode
    reason_list: ReasonList | None


class WorkItemScaleValueOut(BaseModel):
    """One impact, urgency or priority value."""

    scale: Scale
    code: str
    rank: int
    colour: str | None
    labels: dict[str, str] | None


class WorkItemReasonOut(BaseModel):
    """One reason of a pick list (retired ones included, marked: they still label records)."""

    list: ReasonList
    code: str
    labels: dict[str, str] | None
    sort_order: int = 0
    colour: str | None = None
    disabled: bool = False


class WorkItemListValueOut(BaseModel):
    """One value of a level or closure-code list (retired ones included, marked)."""

    code: str
    labels: dict[str, str] | None = Field(description="Null: labelled by the UI from the code.")
    sort_order: int
    colour: str | None
    disabled: bool


class WorkItemMatrixCellOut(BaseModel):
    """impact x urgency → priority."""

    impact: Impact
    urgency: Urgency
    priority: Priority


def _value(v: ReasonInfo) -> WorkItemListValueOut:
    return WorkItemListValueOut(
        code=v.code,
        labels=v.labels,
        sort_order=v.sort_order,
        colour=v.colour,
        disabled=v.disabled,
    )


class WorkItemCatalogueOut(BaseModel):
    """The tenant's configuration of this type (for forms, filters and labels)."""

    prefix: str
    default_priority: Priority
    default_impact: Impact | None = Field(description="What the create form starts with.")
    default_urgency: Urgency | None = Field(description="What the create form starts with.")
    auto_status_on_assign: bool
    keep_following_on_handover: bool = Field(
        description="Hand-over dialog: 'keep following' starts ticked (D-068)."
    )
    first_response_on: list[FirstResponseAction] = Field(
        description="Which actions stamp the first response (REQ-INC-065)."
    )
    version: int
    statuses: list[WorkItemStatusOut]
    actions: list[WorkItemAction] = Field(description="User actions in their fixed order.")
    transitions: list[WorkItemTransitionOut]
    scales: list[WorkItemScaleValueOut]
    matrix: list[WorkItemMatrixCellOut]
    reasons: list[WorkItemReasonOut]
    levels: list[WorkItemListValueOut] = Field(description="Support levels (REQ-INC-007).")
    closure_codes: list[WorkItemListValueOut] = Field(description="REQ-INC-093.")
    next_number: int = Field(description="The display number the next record gets.")

    @classmethod
    def of(cls, cat: Catalogue) -> "WorkItemCatalogueOut":
        """From the loaded catalogue."""
        return cls(
            prefix=cat.prefix,
            default_priority=Priority(cat.default_priority),
            default_impact=None if cat.default_impact is None else Impact(cat.default_impact),
            default_urgency=None if cat.default_urgency is None else Urgency(cat.default_urgency),
            auto_status_on_assign=cat.auto_status_on_assign,
            keep_following_on_handover=cat.keep_following_on_handover,
            first_response_on=[FirstResponseAction(c) for c in cat.first_response_on],
            version=cat.settings_version,
            statuses=[
                WorkItemStatusOut(
                    code=s.code,
                    category=StatusCategory(s.category),
                    colour=s.colour,
                    labels=s.labels,
                    system=s.system,
                    disabled=s.disabled,
                )
                for s in cat.statuses
            ],
            actions=list(USER_ACTIONS),
            transitions=[
                WorkItemTransitionOut(
                    from_status=t.from_status,
                    action=t.action,
                    to_status=t.to_status,
                    reason_mode=t.reason_mode,
                    reason_list=t.reason_list,
                )
                # Life-cycle order (QA BUG-04): by status, then the fixed action order.
                for t in sorted(
                    cat.lifecycle.transitions.values(),
                    key=lambda t: (
                        [st.code for st in cat.statuses].index(t.from_status),
                        USER_ACTIONS.index(t.action) if t.action in USER_ACTIONS else 99,
                    ),
                )
                if t.action in USER_ACTIONS
            ],
            scales=[
                WorkItemScaleValueOut(
                    scale=Scale(v.scale), code=v.code, rank=v.rank, colour=v.colour, labels=v.labels
                )
                for v in cat.scales
            ],
            matrix=[
                WorkItemMatrixCellOut(impact=Impact(i), urgency=Urgency(u), priority=Priority(p))
                for (i, u), p in sorted(cat.matrix.items())
            ],
            reasons=[
                WorkItemReasonOut(
                    list=ReasonList(r.list),
                    code=r.code,
                    labels=r.labels,
                    sort_order=r.sort_order,
                    colour=r.colour,
                    disabled=r.disabled,
                )
                for r in cat.reasons
                if r.list in REASON_LISTS
            ],
            levels=[_value(v) for v in cat.list_values(PickList.LEVEL)],
            closure_codes=[_value(v) for v in cat.list_values(PickList.CLOSURE_CODE)],
            next_number=cat.last_number + 1,
        )


# Settings that may be cleared with null (the others ignore a null).
NULLABLE_SETTINGS = frozenset({"default_impact", "default_urgency"})


class WorkItemSettingsPatch(BaseModel):
    """Type settings to change (only those sent). If-Match: the catalogue's `version`."""

    model_config = ConfigDict(extra="forbid")

    prefix: str | None = Field(default=None, max_length=6, description="2-6 capital letters.")
    next_number: int | None = Field(
        default=None, ge=1, le=10**15, description="The number the next record gets (never lower)."
    )
    default_priority: Priority | None = None
    default_impact: Impact | None = Field(default=None, description="Null: no default.")
    default_urgency: Urgency | None = Field(default=None, description="Null: no default.")
    auto_status_on_assign: bool | None = None
    keep_following_on_handover: bool | None = None
    first_response_on: list[FirstResponseAction] | None = Field(default=None, max_length=3)


class WorkItemCategoryOut(BaseModel):
    """One node of the category tree."""

    id: uuid.UUID
    parent_id: uuid.UUID | None
    level: int
    code: str | None = Field(description="Seeded nodes: labelled by the UI from this code.")
    labels: dict[str, str] | None = Field(description="Admin nodes: their own translations.")
    sort_order: int
    default_group_id: uuid.UUID | None
    disabled: bool
    version: int

    @classmethod
    def of(cls, node: WorkItemCategory) -> "WorkItemCategoryOut":
        """From a row."""
        return cls(
            id=node.id,
            parent_id=node.parent_id,
            level=node.level,
            code=node.code,
            labels=node.labels,
            sort_order=node.sort_order,
            default_group_id=node.default_group_id,
            disabled=node.disabled_at is not None,
            version=node.version,
        )


class WorkItemCategoryIn(BaseModel):
    """A new node: under `parent_id`, or a new top-level category."""

    model_config = ConfigDict(extra="forbid")

    parent_id: uuid.UUID | None = None
    labels: dict[str, str] = Field(
        description='{"en": "...", "ar": "...", "ur": "..."}; en required.'
    )
    default_group_id: uuid.UUID | None = None


class WorkItemCategoryPatch(BaseModel):
    """Rename / translate, default group, disable."""

    model_config = ConfigDict(extra="forbid")

    labels: dict[str, str] | None = None
    default_group_id: uuid.UUID | None = None
    disabled: bool | None = None


class WorkItemFieldChangeOut(BaseModel):
    """One field of one save. Values are codes, IDs, text or ISO times; the UI labels them."""

    field: str
    old: Any = None
    new: Any = None


class WorkItemHistoryEntryOut(BaseModel):
    """One save: who, when (microseconds), from where, what, why, and which automation."""

    change_id: uuid.UUID
    version: int
    kind: ChangeKind
    occurred_at: datetime
    actor_type: Literal["user", "system"]
    actor_id: str | None
    actor_name: str | None
    source: Source
    reason: str | None
    automation: dict[str, Any] | None = Field(
        description="Set when automation made the change, e.g. {kind: matrix}."
    )
    changes: list[WorkItemFieldChangeOut]
    audit_entry_id: uuid.UUID | None = Field(
        default=None,
        description="The audit entry of this save; only for holders of audit.view (REQ-AUD-006).",
    )

    @classmethod
    def of(
        cls,
        entry: HistoryEntry,
        names: dict[str, str],
        audit: dict[uuid.UUID, uuid.UUID] | None = None,
    ) -> "WorkItemHistoryEntryOut":
        """From a history entry plus resolved actor names (and audit links, if allowed)."""
        return cls(
            change_id=entry.change_id,
            version=entry.version,
            kind=entry.kind,
            occurred_at=entry.occurred_at,
            actor_type="user" if entry.actor_type == "user" else "system",
            actor_id=entry.actor_id,
            actor_name=names.get(entry.actor_id or ""),
            source=entry.source,
            reason=entry.reason,
            automation=entry.automation_ref if isinstance(entry.automation_ref, dict) else None,
            changes=[
                WorkItemFieldChangeOut(field=c.field, old=c.old, new=c.new) for c in entry.changes
            ],
            audit_entry_id=(audit or {}).get(entry.change_id),
        )


class WorkItemHistoryOut(BaseModel):
    """Saves of one record, newest first."""

    items: list[WorkItemHistoryEntryOut]
    next_cursor: str | None
    people: dict[str, PersonOut] = Field(
        default_factory=dict, description="People named in changed values, by user ID."
    )


def _item(row: WorkItem) -> WorkItemListItem:
    return WorkItemListItem.model_validate(row, from_attributes=True)


def _cursor(value: str | None) -> tuple[datetime, uuid.UUID] | None:
    """`<microseconds since epoch>_<change id>` (URL-safe, exact to the microsecond)."""
    if not value:
        return None
    try:
        micros, change = value.split("_", 1)
        moment = datetime.fromtimestamp(0, UTC) + timedelta(microseconds=int(micros))
        return moment, uuid.UUID(change)
    except ValueError as error:
        raise BadRequest(code="invalid_cursor") from error


def _cursor_text(at: datetime, change_id: uuid.UUID) -> str:
    delta = at - datetime.fromtimestamp(0, UTC)
    micros = (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds
    return f"{micros}_{change_id}"


# --- the factory ----------------------------------------------------------------------------------


def build_router(wtype: WorkItemType) -> APIRouter:  # noqa: C901, PLR0915 - one route per operation
    """Every route of one work item type."""
    router = APIRouter(
        prefix=f"/{wtype.path}",
        tags=[wtype.path],
        dependencies=[Depends(rate_limit("work_items"))],
        responses=RESPONSES,
    )
    perm = wtype.permission
    View = Annotated[Subject, Depends(require_permission(perm("view")))]  # noqa: N806 - type alias
    Create = Annotated[Subject, Depends(require_permission(perm("create")))]  # noqa: N806 - type alias
    Edit = Annotated[Subject, Depends(require_permission(perm("edit")))]  # noqa: N806 - type alias
    Assign = Annotated[Subject, Depends(require_permission(perm("assign")))]  # noqa: N806 - type alias
    Take = Annotated[Subject, Depends(require_permission(perm("take")))]  # noqa: N806 - type alias
    Delete = Annotated[Subject, Depends(require_permission(perm("delete")))]  # noqa: N806 - type alias
    Admin = Annotated[Subject, Depends(require_permission("settings.manage"))]  # noqa: N806 - type alias
    Policy = Annotated[PolicyService, Depends(get_policy)]  # noqa: N806 - type alias
    Query_ = Annotated[  # noqa: N806 - type alias
        ListQuery,
        Depends(
            list_query(
                FIELDS,
                extra_parameters=frozenset({"view", "tag"}),
                # Custom fields filter as `custom.<key>` (WP-026), typed per tenant.
                fields_for=lambda session: metadata.filter_fields(
                    session, wtype.code.value, "work_items"
                ),
            )
        ),
    ]
    location = f"/api/v1/{wtype.path}"
    name = wtype.code.replace("_", " ")

    async def _page(
        session: Any,  # noqa: ANN401 - TenantSession (an AsyncSession) from the route
        page: PageResult[WorkItem],
    ) -> WorkItemPage:
        people = sorted(
            {str(u) for r in page.rows for u in (r.requester_id, r.technician_id) if u is not None}
        )
        return WorkItemPage(
            items=[_item(r) for r in page.rows],
            next_cursor=page.next_cursor,
            has_more=page.has_more,
            estimated_total=page.estimated_total,
            people=_people(await user_contacts(session, people)),
        )

    @router.get("", summary=f"List {wtype.path}")
    async def list_items(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and query options
        session: TenantSession,
        query: Query_,
        subject: View,
        request: Request,
        view: Annotated[str | None, Query(description="A built-in view (see /views).")] = None,
        tag: Annotated[str | None, Query(max_length=40)] = None,
    ) -> WorkItemPage:
        """Records you may see. Filter with the DSL or simple parameters, a view and a tag."""
        page = await service.list_page(
            session, subject, wtype, query, view=view, zone=request_zone(request), tag=tag
        )
        return await _page(session, page)

    @router.get("/views", summary=f"Built-in {name} views with counts")
    async def views(
        session: TenantSession, subject: View, request: Request
    ) -> list[WorkItemViewCountOut]:
        """Every built-in view in its fixed order, with how many records you see in it."""
        found = await service.view_counts(session, subject, wtype, zone=request_zone(request))
        return [WorkItemViewCountOut(view=v, count=c, capped=capped) for v, c, capped in found]

    @router.get("/trash", summary=f"{name.capitalize()}s in the trash")
    async def trash(
        session: TenantSession, query: Query_, subject: Delete, request: Request
    ) -> WorkItemPage:
        """Deleted records you may restore (needs the delete permission)."""
        page = await service.list_page(
            session, subject, wtype, query, view=None, zone=request_zone(request), trash=True
        )
        return await _page(session, page)

    @router.get("/assignees", summary="People who can be assigned")
    async def assignees(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and query options
        session: TenantSession,
        subject: View,
        policy: Policy,
        group_id: uuid.UUID | None = None,
        search: Annotated[str | None, Query(max_length=100)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> list[WorkItemAssigneeOut]:
        """Members of `group_id` (or everyone) who can work on these records, with open load."""
        found = await service.assignees(
            session,
            subject,
            wtype,
            policy,
            group_id=group_id,
            search=(search or "").strip() or None,
            limit=limit,
        )
        return [
            WorkItemAssigneeOut(id=u, display_name=n, email=e, open_count=c) for u, n, e, c in found
        ]

    @router.get("/search", summary=f"Search {wtype.path}")
    async def search(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and query options
        session: TenantSession,
        subject: View,
        q: Annotated[
            str | None,
            Query(
                max_length=200,
                description="Display ID, subject or description words, or the requester's name "
                "or email. Word forms (English, Arabic), Urdu word starts and typos match.",
            ),
        ] = None,
        status_category: Annotated[list[StatusCategory], Query()] = [],  # noqa: B006 - FastAPI copies query defaults
        requester_id: uuid.UUID | None = None,
        ids: Annotated[
            list[uuid.UUID] | None,
            Query(max_length=20, description="Only these records (e.g. recently viewed)."),
        ] = None,
        limit: Annotated[int, Query(ge=1, le=search_service.MAX_RESULTS)] = 20,
    ) -> WorkItemSearchOut:
        """Records you may see, exactly as in the lists (REQ-INC-085), best match first.

        Without `q`: the most recently updated (narrowed by the other parameters).
        """
        rows = await search_service.search(
            session,
            subject,
            wtype,
            (q or "").strip() or None,
            status_categories={c.value for c in status_category},
            requester_id=requester_id,
            ids=ids,
            limit=limit,
        )
        people = sorted({str(u) for r in rows for u in (r.requester_id, r.technician_id) if u})
        return WorkItemSearchOut(
            items=[_item(r) for r in rows],
            people=_people(await user_contacts(session, people)),
        )

    @router.get("/lookup/{value}", summary="Find by display ID")
    async def lookup(
        value: str, session: TenantSession, subject: View, response: Response
    ) -> WorkItemOut:
        """`INC-12`, `inc-12` or `12`. Old prefixes keep working after a rename."""
        found = await service.lookup(session, subject, wtype, value[:40])
        set_etag(response, found.record.version)
        return WorkItemOut.of(found)

    @router.get("/settings", summary=f"{name.capitalize()} configuration")
    async def get_settings(
        session: TenantSession, subject: View, response: Response
    ) -> WorkItemCatalogueOut:
        """Statuses, actions, transitions, scales, the matrix, reasons and the prefix."""
        del subject
        cat = await settings_service.get_catalogue(session, wtype)
        set_etag(response, cat.settings_version)
        return WorkItemCatalogueOut.of(cat)

    @router.patch("/settings", summary=f"Change {name} settings", responses=CONFLICT)
    async def patch_settings(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        body: WorkItemSettingsPatch,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Annotated[
            AuditNote, audited(f"{name}.settings_changed", object_type=f"{name}_settings")
        ],
    ) -> WorkItemCatalogueOut:
        """Prefix, default priority and the automatic status moves on assignment."""
        note.details = {"changed_fields": sorted(body.model_fields_set)}
        cat = await settings_service.update_settings(
            session,
            wtype,
            expected_version=version,
            values={
                k: v
                for k, v in body.model_dump(include=body.model_fields_set).items()
                if v is not None or k in NULLABLE_SETTINGS
            },
            source=source_of(request),
            user_id=subject.user_id,
        )
        set_etag(response, cat.settings_version)
        return WorkItemCatalogueOut.of(cat)

    @router.get("/categories", summary="Category tree")
    async def categories(session: TenantSession, subject: View) -> list[WorkItemCategoryOut]:
        """Every node, parents first; disabled nodes are marked, not hidden."""
        del subject
        return [
            WorkItemCategoryOut.of(n)
            for n in await settings_service.list_categories(session, wtype)
        ]

    @router.post("/categories", summary="Add a category", status_code=status.HTTP_201_CREATED)
    async def create_category(
        body: WorkItemCategoryIn,
        session: TenantSession,
        subject: Admin,
        request: Request,
        note: Annotated[
            AuditNote, audited(f"{name}.category_created", object_type=f"{name}_category")
        ],
    ) -> WorkItemCategoryOut:
        """A new node (at most three levels)."""
        del subject
        node = await settings_service.create_category(
            session,
            wtype,
            parent_id=body.parent_id,
            labels=body.labels,
            default_group_id=body.default_group_id,
            source=source_of(request),
        )
        out = WorkItemCategoryOut.of(node)
        note.object_id = str(out.id)
        note.details = {"parent_id": body.parent_id}
        return out

    @router.patch("/categories/{category_id}", summary="Change a category", responses=CONFLICT)
    async def patch_category(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        category_id: uuid.UUID,
        body: WorkItemCategoryPatch,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        request: Request,
        note: Annotated[
            AuditNote,
            audited(
                f"{name}.category_changed",
                object_type=f"{name}_category",
                object_param="category_id",
            ),
        ],
    ) -> WorkItemCategoryOut:
        """Rename or translate, set its default group, disable or enable."""
        del subject
        note.details = {"changed_fields": sorted(body.model_fields_set)}
        node = await settings_service.update_category(
            session,
            wtype,
            category_id,
            expected_version=version,
            values=body.model_dump(include=body.model_fields_set),
            source=source_of(request),
        )
        return WorkItemCategoryOut.of(node)

    add_collection_routes(router, wtype)
    add_settings_routes(router, wtype, WorkItemCatalogueOut)

    @router.post(
        "",
        summary=f"Create {'an' if name[0] in 'aeiou' else 'a'} {name}",
        status_code=status.HTTP_201_CREATED,
        response_model=WorkItemOut,
        responses=CONFLICT,
    )
    async def create(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        body: WorkItemIn,
        session: TenantSession,
        subject: Create,
        idempotency: Idempotency,
        request: Request,
        policy: Policy,
    ) -> Response:
        """A new record. Send an Idempotency-Key: a retried request returns the same 201."""

        async def run() -> Created:
            view = await service.create(
                session,
                subject,
                wtype,
                body.model_dump(exclude_unset=True),
                source=source_of(request),
                holders=policy,
            )
            out = WorkItemOut.of(view)
            return Created(
                body=out, headers={"Location": f"{location}/{out.id}", "ETag": f'"{out.version}"'}
            )

        return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)

    @router.get("/{record_id}", summary=f"Get {'an' if name[0] in 'aeiou' else 'a'} {name}")
    async def get(
        record_id: uuid.UUID, session: TenantSession, subject: View, response: Response
    ) -> WorkItemOut:
        """One record within your view scope (404 otherwise, even if it exists)."""
        found = await service.get(session, subject, wtype, record_id)
        set_etag(response, found.record.version)
        return WorkItemOut.of(found)

    @router.patch("/{record_id}", summary="Edit fields", responses=CONFLICT)
    async def edit(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: WorkItemPatch,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Edit,
        response: Response,
        request: Request,
    ) -> WorkItemOut:
        """Change the fields you send. Needs If-Match. Priority by hand needs a reason."""
        view = await service.update(
            session,
            subject,
            wtype,
            record_id,
            expected_version=version,
            values=body.model_dump(include=body.model_fields_set),
            source=source_of(request),
        )
        set_etag(response, view.record.version)
        return WorkItemOut.of(view)

    @router.post("/{record_id}/actions/{action}", summary="Run a status action", responses=CONFLICT)
    async def act(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        action: WorkItemAction,
        version: ExpectedVersion,
        session: TenantSession,
        subject: View,
        response: Response,
        request: Request,
        policy: Policy,
        body: WorkItemTransitionIn | None = None,
    ) -> WorkItemOut:
        """Only the actions the life cycle allows from the current status; some need a reason.

        Start work on an unassigned record takes it for you first (`group_id` as with Take).
        """
        view = await service.transition(
            session,
            subject,
            wtype,
            record_id,
            action,
            expected_version=version,
            reason_code=body.reason_code if body else None,
            reason_text=body.reason_text if body else None,
            source=source_of(request),
            holders=policy,
            group_id=body.group_id if body else None,
        )
        set_etag(response, view.record.version)
        return WorkItemOut.of(view)

    @router.post("/{record_id}/assign", summary="Assign or reassign", responses=CONFLICT)
    async def assign(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: WorkItemAssignIn,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Assign,
        response: Response,
        request: Request,
        policy: Policy,
    ) -> WorkItemOut:
        """Set group and technician. A move out of your reach needs `confirm_lose_access`."""
        view = await service.assign(
            session,
            subject,
            wtype,
            record_id,
            expected_version=version,
            group_id=body.group_id,
            technician_id=body.technician_id,
            reason_code=body.reason_code,
            reason_text=body.reason_text,
            confirm_lose_access=body.confirm_lose_access,
            keep_following=body.keep_following,
            source=source_of(request),
            holders=policy,
        )
        set_etag(response, view.record.version)
        return WorkItemOut.of(view)

    @router.post("/{record_id}/take", summary="Take it yourself", responses=CONFLICT)
    async def take(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Take,
        response: Response,
        request: Request,
        policy: Policy,
        body: WorkItemTakeIn | None = None,
    ) -> WorkItemOut:
        """You become the technician; with no group, your only group is set (or you choose)."""
        view = await service.take(
            session,
            subject,
            wtype,
            record_id,
            expected_version=version,
            group_id=body.group_id if body else None,
            source=source_of(request),
            holders=policy,
        )
        set_etag(response, view.record.version)
        return WorkItemOut.of(view)

    @router.delete(
        "/{record_id}",
        summary="Move to the trash",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=CONFLICT,
        dependencies=[audited(f"{name}.deleted", object_type=name, object_param="record_id")],
    )
    async def delete(
        record_id: uuid.UUID,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Delete,
        request: Request,
    ) -> Response:
        """Soft delete: recoverable from the trash with POST …/restore."""
        await service.remove(
            session, subject, wtype, record_id, expected_version=version, source=source_of(request)
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/{record_id}/restore",
        summary="Restore from the trash",
        responses=CONFLICT,
        dependencies=[audited(f"{name}.restored", object_type=name, object_param="record_id")],
    )
    async def restore(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Delete,
        response: Response,
        request: Request,
    ) -> WorkItemOut:
        """Take it out of the trash, as it was."""
        view = await service.restore(
            session, subject, wtype, record_id, expected_version=version, source=source_of(request)
        )
        set_etag(response, view.record.version)
        return WorkItemOut.of(view)

    @router.get("/{record_id}/history", summary="History")
    async def history(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and query options
        record_id: uuid.UUID,
        session: TenantSession,
        subject: View,
        cursor: Annotated[
            str | None, Query(description="next_cursor of the previous page.")
        ] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        actors: Annotated[Actors, Query(description="people, automation or all")] = "all",
    ) -> WorkItemHistoryOut:
        """Every save, newest first, in true order: who, when, from where, what, why."""
        entries, next_cursor, names, people = await service.history(
            session, subject, wtype, record_id, before=_cursor(cursor), limit=limit, actors=actors
        )
        audit = (
            await entries_for_changes(session, [e.change_id for e in entries])
            if subject.holds("audit.view")
            else {}
        )
        return WorkItemHistoryOut(
            items=[WorkItemHistoryEntryOut.of(e, names, audit) for e in entries],
            next_cursor=None if next_cursor is None else _cursor_text(*next_cursor),
            people=_people(people),
        )

    add_record_routes(router, wtype)
    return router
