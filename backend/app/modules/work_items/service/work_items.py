"""Work item use cases (WP-020; ADR-026): one engine, called per type by the routers.

Each write, in one transaction (docs/architecture/module-template.md §4):

1. the record must be visible to the caller (else 404), and the action's permission must reach
   it (else 403);
2. the input is validated (422 with field codes), references included;
3. the row is updated with optimistic concurrency (409 explains who changed what);
4. visibility is checked again: a write may not move a record out of the writer's reach
   unless it is an explicit hand-over the writer confirmed (D-053, `would_lose_access`); by
   default they keep following it with access (D-068, `keep_following`);
5. field history (with source, reason, and which automation did what);
6. the outbox event.

Status changes only through life-cycle actions (REQ-INC-046); assignment runs the automatic
status moves (REQ-INC-050); priority comes from the matrix unless set by hand with a reason
(REQ-INC-009/010).
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any, Literal, Protocol

from sqlalchemy import ColumnElement, Select, and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, NotFound, PermissionDenied, ValidationFailed
from app.modules import metadata, service_catalog
from app.modules.automation import (
    TRANSITION_NOT_FOR_YOU as NOT_FOR_YOU,
)
from app.modules.automation import (
    People,
    Relative,
    RuleEvent,
    log_trace,
    record_runs,
    transition_audience,
    transition_refusal,
    transition_settings,
)
from app.modules.identity_access import (
    Placement,
    RoleName,
    Subject,
    authorize_stored,
    direct_reports,
    display_names,
    person_placement,
    role_names,
    scope_filter,
    user_contacts,
    user_names,
)
from app.modules.organization import (
    default_desk_id,
    existing_departments,
    existing_unit_ids,
    memberships,
    unit_heads,
    users_in_groups,
)
from app.modules.work_items.domain import releases as release_rules
from app.modules.work_items.domain import service_requests as sr_rules
from app.modules.work_items.domain.classification import (
    PRIORITY_REASON_MAX,
    Impact,
    Priority,
    PrioritySource,
    Urgency,
    compute_priority,
)
from app.modules.work_items.domain.closure import MOVE_FIELDS, missing_fields, within_reopen_window
from app.modules.work_items.domain.conversation import FollowReason
from app.modules.work_items.domain.lifecycle import (
    FINAL_CATEGORIES,
    PauseClock,
    ReasonList,
    ReasonMode,
    StatusCategory,
    WorkItemAction,
    after_assignment,
    move_pause_clock,
    reason_problems,
)
from app.modules.work_items.domain.service_requests import ApprovalStatus
from app.modules.work_items.domain.stages import (
    DEFAULT_PATH,
    Move,
    MoveRefused,
    RailStage,
    SetBy,
    StatusTransitionDef,
    plan_move,
)
from app.modules.work_items.domain.templates import PickList, clean_impact_details, is_custom
from app.modules.work_items.domain.types import (
    DESCRIPTION_MAX,
    STANDARD_LIFECYCLE,
    Channel,
    WorkItemType,
    WorkItemTypeCode,
    channel_problems,
    clean_subject,
    clean_tags,
    parse_display_id,
)
from app.modules.work_items.events import (
    Audience,
    WorkItemAssigned,
    WorkItemCreated,
    WorkItemDeleted,
    WorkItemRestored,
    WorkItemStageChanged,
    WorkItemStatusChanged,
    WorkItemUpdated,
)
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemCategory,
    WorkItemConversation,
    WorkItemFollower,
    WorkItemReleaseDetails,
)
from app.modules.work_items.service import approval_stage, automation, closing, followers, templates
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service import sla as sla_glue
from app.modules.work_items.service import stages as stage_service
from app.modules.work_items.service.access import RESOURCE
from app.modules.work_items.service.catalogue import Catalogue
from app.shared.api.listing import ListQuery, PageResult, paginate
from app.shared.db.display_ids import next_display_number
from app.shared.db.repository import Repository
from app.shared.domain import InvalidTransition
from app.shared.events import record_event
from app.shared.history import (
    Actors,
    Change,
    FieldChange,
    HistoryCursor,
    HistoryEntry,
    Source,
    count_saves,
    explain_conflict,
    history_entries,
    record_changes,
)
from app.shared.ids import new_id
from app.shared.reporting.names import names_resolver
from app.shared.richtext import is_blank, sanitize_html

RECORD_TYPE = followers.RECORD_TYPE
OPEN_CATEGORIES = (StatusCategory.OPEN, StatusCategory.PAUSED)

# Why an action is disabled right now (the UI labels them as `action_reason.<code>`).
NOT_FROM_STATUS = "not_from_status"
NO_PERMISSION = "no_permission"
OUT_OF_SCOPE = "out_of_scope"
RECORD_CLOSED = "record_closed"
ALREADY_YOURS = "already_yours"
ASSIGNED_TO_OTHER = "assigned_to_other"
# Start work on an unassigned record takes it first (QA BUG-05); this user may not take it.
CANNOT_TAKE = "cannot_take"

# Which permission runs which status action.
ACTION_PERMISSION: Mapping[WorkItemAction, str] = {
    WorkItemAction.START_WORK: "edit",
    # problems (WP-044a): working the problem through its analysis
    WorkItemAction.INVESTIGATE: "edit",
    WorkItemAction.CONFIRM_ROOT_CAUSE: "edit",
    WorkItemAction.AWAIT_FIX: "edit",
    WorkItemAction.ANALYSE: "edit",
    WorkItemAction.START_REVIEW: "edit",
    WorkItemAction.HOLD: "edit",
    WorkItemAction.WAIT_REQUESTER: "edit",
    WorkItemAction.WAIT_THIRD_PARTY: "edit",
    WorkItemAction.RESUME: "edit",
    WorkItemAction.RESOLVE: "resolve",
    WorkItemAction.CLOSE: "close",
    WorkItemAction.REOPEN: "reopen",
    WorkItemAction.CANCEL: "cancel",
    WorkItemAction.UNDO_CANCEL: "cancel",
}
# Record operations besides status actions, in the order the UI shows them.
OPERATIONS = ("edit", "assign", "take", "change_priority", "delete")
# The conversation's actions (WP-020b); allowed on closed records too (a note after closing).
CONVERSATION_ACTIONS = ("add_note", "reply", "manage_followers")


class PermissionHolders(Protocol):
    """The part of the policy service a technician check needs (identity_access)."""

    async def user_holds(
        self, session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, permission: str
    ) -> bool:
        """Whether one user holds the permission."""
        ...

    async def holders(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        permission: str,
        *,
        search: str | None = ...,
        limit: int = ...,
    ) -> list[tuple[uuid.UUID, str]]:
        """Active users holding the permission: (id, display name)."""
        ...


class WorkItemRepository(Repository[WorkItem]):
    """Work items of the session's tenant."""

    model = WorkItem


# --- views ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionState:
    """One action as this user may use it now (disabled ones carry the reason)."""

    action: str
    allowed: bool
    reason: str | None = None
    reason_mode: str = ReasonMode.NONE
    reason_list: str | None = None
    # Asked before the move runs, per language (REQ-WF-003 "during").
    confirmation: Mapping[str, str] | None = None
    # Refused as "not for you": who may run it (QA WP-029 C2).
    allowed_for: "AllowedFor | None" = None
    # Resolve and close: record fields the closure rules still need (the move asks for its own
    # field, the resolution or the closure code); WP-020f, REQ-INC-094.
    missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class AllowedFor:
    """Who may run a transition: roles, group names, people on the record (codes, labelled)."""

    roles: list[RoleName]
    groups: list[str]
    relatives: list[str]


@dataclass(frozen=True)
class WorkItemView:
    """Everything staff see about one work item."""

    record: WorkItem
    actions: list[ActionState]
    operations: list[ActionState]
    history_count: int
    # {user id: (display name, email)} of the people on the record.
    names: dict[str, tuple[str, str]] = field(default_factory=dict)
    # False right after the writer handed the record out of their own reach (D-053).
    visible: bool = True
    # add_note, reply, manage_followers: whether this user may, and why not (WP-020b).
    conversation: list[ActionState] = field(default_factory=list)
    following: bool = False
    conversation_count: int = 0
    # Fields this subject may not read (problems: the root cause without view_root_cause).
    hidden: frozenset[str] = frozenset()
    # Problems: who last changed each analysis field, and when (REQ-PRB-030).
    analysis_changes: tuple["AnalysisChange", ...] = ()


def _now() -> datetime:
    return datetime.now(UTC)


def _errors(problems: Sequence[tuple[str, str]], **params: Any) -> ValidationFailed:  # noqa: ANN401 - problem params
    return ValidationFailed(
        errors=[
            FieldError(
                field=f"body.{name}",
                code=code,
                message_key=f"errors.field.{code}",
                params=params.get(name, {}),
            )
            for name, code in problems
        ]
    )


def _not_found(wtype: WorkItemType) -> NotFound:
    del wtype  # one code for every type: the UI says "not found or not visible"
    return NotFound(code="work_item_not_found")


def _rows(wtype: WorkItemType, *, trash: bool = False) -> Select[Any]:
    deleted = WorkItem.deleted_at.is_not(None) if trash else WorkItem.deleted_at.is_(None)
    return select(WorkItem).where(WorkItem.type == wtype.code, deleted)


async def _may(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, action: str, record_id: uuid.UUID
) -> bool:
    permission = wtype.permission(action)
    if not subject.holds(permission):
        return False
    return bool(
        await authorize_stored(session, subject, permission, RESOURCE, WorkItem.id, record_id)
    )


async def _reason_for(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, action: str, record_id: uuid.UUID
) -> str | None:
    """None when allowed, else no_permission / out_of_scope."""
    if not subject.holds(wtype.permission(action)):
        return NO_PERMISSION
    if not await _may(session, subject, wtype, action, record_id):
        return OUT_OF_SCOPE
    return None


async def _relatives(
    session: AsyncSession, subject: Subject, record: WorkItem
) -> frozenset[Relative]:
    """Who the subject is to the record, for "who may run" (REQ-WF-004)."""
    me = subject.user_id
    found: set[Relative] = set()
    if me in {record.requester_id, record.on_behalf_of_id}:
        found.add(Relative.REQUESTER)
    if me == record.technician_id:
        found.add(Relative.ASSIGNEE)
    lead, head = await unit_heads(session, record.group_id, record.department_id)
    if me == lead:
        found.add(Relative.GROUP_HEAD)
    if me == head:
        found.add(Relative.DEPARTMENT_HEAD)
    if me == (await person_placement(session, record.requester_id)).manager_id:
        found.add(Relative.REQUESTER_MANAGER)
    return frozenset(found)


class _Transitions:
    """A record's transition settings, checked for one subject (loaded once per view)."""

    def __init__(self, session: AsyncSession, subject: Subject, record: WorkItem) -> None:
        self.session, self.subject, self.record = session, subject, record
        self._rows: dict[str, Any] | None = None
        self._person: People | None = None

    async def _row(self, action: str) -> Any:  # noqa: ANN401 - automation's settings row
        if self._rows is None:
            rows = await transition_settings(self.session, self.record.type)
            self._rows = {row.action: row for row in rows}
        return self._rows.get(action)

    async def confirmation(self, action: str) -> Mapping[str, str] | None:
        row = await self._row(action)
        return None if row is None else row.confirmation

    async def refusal(self, action: str) -> str | None:
        row = await self._row(action)
        if row is None:
            return None
        if self._person is None:
            self._person = People(
                user_id=str(self.subject.user_id),
                role_keys=self.subject.role_keys,
                group_ids=frozenset(str(g) for g in self.subject.group_ids),
                relatives=await _relatives(self.session, self.subject, self.record),
            )
        facts = {
            **_snapshot(self.record),
            "status": self.record.status,
            "status_category": self.record.status_category,
            **await automation.requester_facts(self.session, self.record.requester_id),
        }
        return transition_refusal(row, self._person, facts)

    async def allowed_for(self, action: str) -> AllowedFor | None:
        """Who the action is limited to, named (QA WP-029 C2)."""
        row = await self._row(action)
        if row is None:
            return None
        limited = transition_audience(row)
        resolver = names_resolver("group")
        groups = (
            await resolver(self.session, limited.group_ids, "en", "group_id")
            if resolver is not None and limited.group_ids
            else {}
        )
        return AllowedFor(
            roles=await role_names(self.session, limited.roles),
            groups=[groups[g] for g in limited.group_ids if g in groups],
            relatives=limited.relatives,
        )


async def _view(  # noqa: C901 - one state per action and operation, flat
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record: WorkItem
) -> WorkItemView:
    cat = await config.load(session, wtype)
    lifecycle = cat.lifecycle_of(record.lifecycle)
    final = StatusCategory(record.status_category) in FINAL_CATEGORIES
    allowed_now = set(lifecycle.actions_from(record.status))
    reasons: dict[str, str | None] = {}

    async def reason(permission_action: str) -> str | None:
        if permission_action not in reasons:
            reasons[permission_action] = await _reason_for(
                session, subject, wtype, permission_action, record.id
            )
        return reasons[permission_action]

    transitions = _Transitions(session, subject, record)
    actions: list[ActionState] = []
    for action in lifecycle.used_actions():
        transition = lifecycle.transitions.get((record.status, action))
        mode = transition.reason_mode if transition else ReasonMode.NONE
        reason_list = transition.reason_list if transition else None
        if action not in allowed_now:
            actions.append(ActionState(action, allowed=False, reason=NOT_FROM_STATUS))
            continue
        refused = await reason(ACTION_PERMISSION[action])
        if (
            refused is None
            and action == WorkItemAction.START_WORK
            and record.technician_id is None
            and await reason("take") is not None
        ):
            refused = CANNOT_TAKE
        if refused is None:
            # Who may run it and when it is offered (REQ-WF-003, 004).
            refused = await transitions.refusal(action.value)
        actions.append(
            ActionState(
                action,
                allowed=refused is None,
                reason=refused,
                reason_mode=mode,
                reason_list=reason_list,
                confirmation=await transitions.confirmation(action.value),
                allowed_for=(
                    await transitions.allowed_for(action.value) if refused == NOT_FOR_YOU else None
                ),
                missing=tuple(
                    name
                    for name in await closing.missing_for(session, cat, record, action)
                    if name not in MOVE_FIELDS
                ),
            )
        )
    operations: list[ActionState] = []
    for op in OPERATIONS:
        refused = await reason(op)
        if refused is None and final and op != "delete":
            refused = RECORD_CLOSED
        if refused is None and op == "take":
            if record.technician_id == subject.user_id:
                refused = ALREADY_YOURS
            elif record.technician_id is not None:
                refused = ASSIGNED_TO_OTHER
        operations.append(ActionState(op, allowed=refused is None, reason=refused))
    if wtype.code is WorkItemTypeCode.PROBLEM:  # the analysis and solution rights (WP-044b)
        for op in ("edit_analysis", "edit_solution", "mark_known_error"):
            refused = await reason(op)
            if refused is None and final:
                refused = RECORD_CLOSED
            operations.append(ActionState(op, allowed=refused is None, reason=refused))
    hidden = await hidden_fields(session, subject, wtype, record.id)
    analysis = (
        await _analysis_changes(session, record.id, hidden)
        if wtype.code is WorkItemTypeCode.PROBLEM
        else ()
    )
    people = [
        str(u)
        for u in (
            record.requester_id,
            record.on_behalf_of_id,
            record.technician_id,
            record.created_by,
            record.updated_by,
        )
        if u is not None
    ] + [v for v in (record.custom or {}).values() if _is_uuid(v)]  # custom person fields
    people += [c.actor_id for c in analysis if c.actor_id is not None]
    conversation = [
        ActionState(name, allowed=(refused := await reason(name)) is None, reason=refused)
        for name in CONVERSATION_ACTIONS
    ]
    entries = await session.scalar(
        select(func.count())
        .select_from(WorkItemConversation)
        .where(
            WorkItemConversation.work_item_id == record.id,
            WorkItemConversation.deleted_at.is_(None),
        )
    )
    return WorkItemView(
        record=record,
        actions=actions,
        operations=operations,
        history_count=await count_saves(session, RECORD_TYPE, record.id),
        names=await user_contacts(session, people),
        conversation=conversation,
        following=await followers.current(session, record.id, subject.user_id) is not None,
        conversation_count=int(entries or 0),
        hidden=hidden,
        analysis_changes=analysis,
    )


async def _visible(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> WorkItem:
    """The live record if the subject may view it, else 404 (never 403: no existence leak)."""
    record: WorkItem | None = await session.scalar(_rows(wtype).where(WorkItem.id == record_id))
    if record is None or not await _may(session, subject, wtype, "view", record_id):
        raise _not_found(wtype)
    return record


async def _for_action(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, action: str, record_id: uuid.UUID
) -> WorkItem:
    """Visible (404) and the action's permission reaches it (403 with the reason)."""
    record = await _visible(session, subject, wtype, record_id)
    refused = await _reason_for(session, subject, wtype, action, record_id)
    if refused is not None:
        raise PermissionDenied(params={"permission": wtype.permission(action), "reason": refused})
    return record


# --- reading --------------------------------------------------------------------------------------


async def get(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> WorkItemView:
    """One record within the subject's view scope (else 404)."""
    return await _view(session, subject, wtype, await _visible(session, subject, wtype, record_id))


async def lookup(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, value: str
) -> WorkItemView:
    """By display ID: `INC-12`, `inc-12` or `12` (old prefixes keep working, REQ-WI-002)."""
    cat = await config.load(session, wtype)
    prefix, number = parse_display_id(value, cat.prefix)
    if number is None:
        raise _not_found(wtype)
    record = await session.scalar(_rows(wtype).where(WorkItem.display_number == number))
    if record is None:
        raise _not_found(wtype)
    stored_prefix = record.display_id.rsplit("-", 1)[0]
    if prefix is not None and prefix not in {stored_prefix, cat.prefix}:
        raise _not_found(wtype)
    if not await _may(session, subject, wtype, "view", record.id):
        raise _not_found(wtype)
    return await _view(session, subject, wtype, record)


# Built-in views (REQ-INC-105). Each is a predicate over the subject; the scope filter applies on
# top, so a view never shows more than the subject may see.
def _open() -> ColumnElement[bool]:
    return WorkItem.status_category.in_(OPEN_CATEGORIES)


def _start_of_today(zone: tzinfo, now: datetime) -> datetime:
    local = now.astimezone(zone)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


async def views_for(
    session: AsyncSession, subject: Subject, *, zone: tzinfo
) -> dict[str, ColumnElement[bool]]:
    """`view_predicates` for the subject now, with the people the views need looked up."""
    reports = await direct_reports(session, subject.user_id)
    return view_predicates(subject, zone=zone, now=_now(), reports=reports)


def view_predicates(
    subject: Subject,
    *,
    zone: tzinfo,
    now: datetime,
    reports: Sequence[uuid.UUID] = (),
) -> dict[str, ColumnElement[bool]]:
    """Code → predicate of every built-in view, in the order the UI lists them.

    `reports` are the subject's direct reports (people whose manager they are). Overdue and due
    today read the resolution due time the SLA module fills; "shared with me" is a follow that
    grants access (D-068), which only a hand-over (and later, sharing) gives.
    """
    groups = subject.group_ids
    today = _start_of_today(zone, now)
    tomorrow = today + timedelta(days=1)
    following = select(WorkItemFollower.work_item_id).where(
        WorkItemFollower.user_id == subject.user_id, WorkItemFollower.deleted_at.is_(None)
    )
    return {
        "open": _open(),
        "my_open": and_(_open(), WorkItem.technician_id == subject.user_id),
        "unassigned": and_(_open(), WorkItem.technician_id.is_(None)),
        "my_groups_open": and_(_open(), WorkItem.group_id.in_(groups))
        if groups
        else WorkItem.id.is_(None),
        "overdue": and_(_open(), WorkItem.resolution_due_at < now),
        "due_today": and_(
            _open(), WorkItem.resolution_due_at >= now, WorkItem.resolution_due_at < tomorrow
        ),
        "waiting": WorkItem.status_category == StatusCategory.PAUSED,
        "resolved": WorkItem.status_category == StatusCategory.RESOLVED,
        "created_today": and_(WorkItem.created_at >= today, WorkItem.created_at < tomorrow),
        "updated_by_me": WorkItem.updated_by == subject.user_id,
        "followed_by_me": WorkItem.id.in_(following),
        "shared_with_me": WorkItem.id.in_(
            following.where(WorkItemFollower.grants_access.is_(True))
        ),
        "from_my_reports": and_(_open(), WorkItem.requester_id.in_(reports))
        if reports
        else WorkItem.id.is_(None),
        "without_sla": and_(_open(), WorkItem.sla_policy_id.is_(None)),
        # REQ-SLA-019 AC2 and REQ-INC-011 AC3: exactly the records in warning, and the open
        # records with a breached target, both live (the waker stamps the record).
        "about_to_breach": and_(
            _open(),
            or_(
                WorkItem.first_response_sla_state == "warning",
                WorkItem.resolution_sla_state == "warning",
            ),
        ),
        "breached": and_(
            _open(), or_(WorkItem.first_response_breached, WorkItem.resolution_breached)
        ),
        "closed": WorkItem.status_category == StatusCategory.CLOSED,
        "canceled": WorkItem.status_category == StatusCategory.CANCELED,
        # Service requests (WP-030, REQ-SR-009): waiting for approval; approved (or needing
        # none) and still open, i.e. waiting to be fulfilled.
        "pending_approval": WorkItem.approval_status == ApprovalStatus.PENDING.value,
        "awaiting_fulfilment": and_(
            _open(),
            WorkItem.approval_status.in_(
                [ApprovalStatus.APPROVED.value, ApprovalStatus.NOT_NEEDED.value]
            ),
        ),
        "all": WorkItem.id.is_not(None),
        **_personal(subject, now=now, today_end=tomorrow),
    }


# The filter DSL equivalent of each view (WP-020d), for what takes a filter and not a view: the
# list's export through reports. NOT_EXPRESSIBLE: the view needs something the DSL cannot say.
NOT_EXPRESSIBLE = "not_expressible"
_LIST_MAX = 100  # the DSL's longest `in` list


def _cond(field: str, op: str, value: Any = None) -> dict[str, Any]:  # noqa: ANN401 - JSON value
    return (
        {"field": field, "op": op} if value is None else {"field": field, "op": op, "value": value}
    )


def _all(*nodes: dict[str, Any]) -> dict[str, Any]:
    return {"and": list(nodes)}


async def view_filters(
    session: AsyncSession, subject: Subject
) -> dict[str, dict[str, Any] | str | None]:
    """Code → the view as a DSL filter (None: no condition), or NOT_EXPRESSIBLE.

    Each equivalent returns exactly the view's rows; a test holds them together. Relative dates
    ("today", "before now") are computed in the requester's time zone, as the views are.
    """
    me = str(subject.user_id)
    open_ = _cond("status_category", "in", [c.value for c in OPEN_CATEGORIES])
    nothing = _cond("id", op="is_null")
    mine = _cond("technician_id", "eq", me)
    groups = sorted(str(g) for g in subject.group_ids)
    in_groups: dict[str, Any] | str = (
        _cond("group_id", "in", groups) if len(groups) <= _LIST_MAX else NOT_EXPRESSIBLE
    )

    def listed(values: Sequence[uuid.UUID], field: str = "id") -> dict[str, Any] | str:
        if not values:
            return nothing
        if len(values) > _LIST_MAX:
            return NOT_EXPRESSIBLE
        return _cond(field, "in", sorted(str(v) for v in values))

    def both(left: dict[str, Any], right: dict[str, Any] | str) -> dict[str, Any] | str:
        return right if isinstance(right, str) else _all(left, right)

    following = select(WorkItemFollower.work_item_id).where(
        WorkItemFollower.user_id == subject.user_id, WorkItemFollower.deleted_at.is_(None)
    )
    followed = list(await session.scalars(following.limit(_LIST_MAX + 1)))
    shared = list(
        await session.scalars(
            following.where(WorkItemFollower.grants_access.is_(True)).limit(_LIST_MAX + 1)
        )
    )
    reports = await direct_reports(session, subject.user_id)
    due_today = _all(
        open_, _cond("resolution_due_at", op="after_now"), _cond("resolution_due_at", op="today")
    )
    return {
        "open": open_,
        "my_open": _all(open_, mine),
        "unassigned": _all(open_, _cond("technician_id", op="is_null")),
        "my_groups_open": both(open_, in_groups) if groups else nothing,
        "overdue": _all(open_, _cond("resolution_due_at", op="before_now")),
        "due_today": due_today,
        "waiting": _cond("status_category", "eq", StatusCategory.PAUSED.value),
        "resolved": _cond("status_category", "eq", StatusCategory.RESOLVED.value),
        "created_today": _cond("created_at", op="today"),
        "updated_by_me": _cond("updated_by", "eq", me),
        "followed_by_me": listed(followed),
        "shared_with_me": listed(shared),
        "from_my_reports": both(open_, listed(reports, "requester_id")) if reports else nothing,
        "without_sla": _all(open_, _cond("sla_policy_id", op="is_null")),
        "about_to_breach": _all(
            open_,
            {
                "or": [
                    _cond("first_response_sla_state", "eq", "warning"),
                    _cond("resolution_sla_state", "eq", "warning"),
                ]
            },
        ),
        "breached": _all(
            open_,
            {
                "or": [
                    _cond("first_response_breached", "eq", value=True),
                    _cond("resolution_breached", "eq", value=True),
                ]
            },
        ),
        "closed": _cond("status_category", "eq", StatusCategory.CLOSED.value),
        "canceled": _cond("status_category", "eq", StatusCategory.CANCELED.value),
        "pending_approval": _cond("approval_status", "eq", ApprovalStatus.PENDING.value),
        "awaiting_fulfilment": _all(
            open_,
            {
                "field": "approval_status",
                "op": "in",
                "value": [ApprovalStatus.APPROVED.value, ApprovalStatus.NOT_NEEDED.value],
            },
        ),
        "all": None,
        "my_overdue": _all(mine, open_, _cond("resolution_due_at", op="before_now")),
        "my_due_today": _all(mine, due_today),
        "waiting_on_me": _all(mine, _cond("status_category", "eq", StatusCategory.OPEN.value)),
        "updated_by_others": NOT_EXPRESSIBLE,  # "changed or written by someone else" needs SQL
        "unassigned_in_my_groups": both(
            _all(open_, _cond("technician_id", op="is_null")), in_groups
        )
        if groups
        else nothing,
    }


# Personal counters (REQ-INC-128): each is also a view of the same code (not listed in /views).
COUNTERS = (
    "my_overdue",
    "my_due_today",
    "waiting_on_me",
    "updated_by_others",
    "unassigned_in_my_groups",
)
RECENT = timedelta(hours=24)


def _personal(
    subject: Subject, *, now: datetime, today_end: datetime
) -> dict[str, ColumnElement[bool]]:
    """The personal counters' predicates.

    Overdue and due today read the resolution due time, which the SLA module fills (WP-025);
    "pending my approval" comes with approvals (WP-030). "Updated by others" counts field
    changes and conversation entries by someone else in the last 24 hours on records the user
    is assigned to or follows.
    """
    mine = WorkItem.technician_id == subject.user_id
    active = _open()
    followed = WorkItem.id.in_(
        select(WorkItemFollower.work_item_id).where(
            WorkItemFollower.user_id == subject.user_id, WorkItemFollower.deleted_at.is_(None)
        )
    )
    since = now - RECENT
    others_wrote = exists(
        select(WorkItemConversation.id).where(
            WorkItemConversation.work_item_id == WorkItem.id,
            WorkItemConversation.created_at >= since,
            WorkItemConversation.created_by != subject.user_id,
        )
    )
    others_changed = and_(WorkItem.updated_at >= since, WorkItem.updated_by != subject.user_id)
    groups = subject.group_ids
    return {
        "my_overdue": and_(mine, active, WorkItem.resolution_due_at < now),
        "my_due_today": and_(
            mine, active, WorkItem.resolution_due_at >= now, WorkItem.resolution_due_at < today_end
        ),
        "waiting_on_me": and_(mine, WorkItem.status_category == StatusCategory.OPEN),
        "updated_by_others": and_(or_(mine, followed), or_(others_changed, others_wrote)),
        "unassigned_in_my_groups": and_(
            active, WorkItem.technician_id.is_(None), WorkItem.group_id.in_(groups)
        )
        if groups
        else WorkItem.id.is_(None),
    }


VIEW_CODES = (
    "open",
    "my_open",
    "unassigned",
    "my_groups_open",
    "overdue",
    "due_today",
    "waiting",
    "resolved",
    "created_today",
    "updated_by_me",
    "followed_by_me",
    "shared_with_me",
    "from_my_reports",
    "without_sla",
    "closed",
    "canceled",
    "all",
)
# Service requests add their approval views (WP-030, REQ-SR-009); incidents never show them.
SR_VIEW_CODES = ("pending_approval", "awaiting_fulfilment")
COUNT_CAP = 1000


def view_codes(wtype: WorkItemType) -> tuple[str, ...]:
    """The built-in views of one type, in the menu's order."""
    if wtype.code is WorkItemTypeCode.SERVICE_REQUEST:
        return (*VIEW_CODES[:-1], *SR_VIEW_CODES, VIEW_CODES[-1])
    return VIEW_CODES


def staff_rows(
    subject: Subject, wtype: WorkItemType, *, trash: bool = False, permission: str = "view"
) -> Select[Any]:
    """Records the subject may see (scope-filtered)."""
    return _rows(wtype, trash=trash).where(
        scope_filter(subject, wtype.permission(permission), RESOURCE)
    )


async def list_page(  # noqa: PLR0913 - the list's filters, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    query: ListQuery,
    *,
    view: str | None,
    zone: tzinfo,
    tag: str | None = None,
    trash: bool = False,
) -> PageResult[WorkItem]:
    """One page of a built-in view (or everything) with the request's filter and sort."""
    if trash:
        statement = staff_rows(subject, wtype, trash=True, permission="delete")
    else:
        await config.ensure_seeded(session, wtype)
        statement = staff_rows(subject, wtype)
    statement = await narrowed(session, subject, statement, view=view, zone=zone, tag=tag)
    return await paginate(session, statement, query)


async def narrowed(  # noqa: PLR0913 - the list's own narrowing, explicit
    session: AsyncSession,
    subject: Subject,
    statement: Select[Any],
    *,
    view: str | None,
    zone: tzinfo,
    tag: str | None,
) -> Select[Any]:
    """`statement` narrowed to a built-in view and a tag, exactly as the list narrows it."""
    if view is not None:
        predicates = await views_for(session, subject, zone=zone)
        if view not in predicates:
            raise _errors([("view", "invalid_choice")])
        statement = statement.where(predicates[view])
    if tag:
        statement = statement.where(WorkItem.tags.contains([tag]))
    return statement


async def view_counts(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, *, zone: tzinfo
) -> list[tuple[str, int, bool]]:
    """(view code, count up to COUNT_CAP, capped) for every built-in view."""
    predicates = await views_for(session, subject, zone=zone)
    base = staff_rows(subject, wtype)
    found: list[tuple[str, int, bool]] = []
    for code in view_codes(wtype):
        limited = base.where(predicates[code]).with_only_columns(WorkItem.id).limit(COUNT_CAP + 1)
        total = int(await session.scalar(select(func.count()).select_from(limited.subquery())) or 0)
        found.append((code, min(total, COUNT_CAP), total > COUNT_CAP))
    return found


# Fields whose history values are user IDs: the page names them (QA BUG-03).
PERSON_FIELDS = frozenset(
    {
        "requester_id",
        "on_behalf_of_id",
        "technician_id",
        "follower",
        "follower_access",
        "task.owner_id",  # WP-020e
    }
)


async def history(  # noqa: PLR0913 - paging options, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    before: HistoryCursor | None,
    limit: int,
    actors: Actors,
) -> tuple[list[HistoryEntry], HistoryCursor | None, dict[str, str], dict[str, tuple[str, str]]]:
    """Saves of a record the subject may see, newest first.

    Plus the actors' names and the people named in changed values (name, email): the History
    tab shows "Technician: (empty) → Tariq", never an ID or a bare "changed".
    """
    await _visible(session, subject, wtype, record_id)
    entries, cursor = await history_entries(
        session, RECORD_TYPE, record_id, before=before, limit=limit, actors=actors
    )
    hidden = await hidden_fields(session, subject, wtype, record_id)
    if hidden:  # the root cause stays out of the history too (D-140 Q7)
        entries = [
            replace(e, changes=[c for c in e.changes if c.field not in hidden]) for e in entries
        ]
    names = await user_names(session, sorted({e.actor_id for e in entries if e.actor_id}))
    named = {
        value
        for e in entries
        for c in e.changes
        if c.field in PERSON_FIELDS or is_custom(c.field)
        for value in (c.old, c.new)
        if isinstance(value, str) and (c.field in PERSON_FIELDS or _is_uuid(value))
    }
    # A worklog's value names its owner (WP-020e).
    named |= {
        str(value["owner_id"])
        for e in entries
        for c in e.changes
        if c.field == "worklog"
        for value in (c.old, c.new)
        if isinstance(value, dict) and value.get("owner_id")
    }
    return entries, cursor, names, await user_contacts(session, sorted(named))


async def assignees(  # noqa: PLR0913 - search options, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    holders: PermissionHolders,
    *,
    group_id: uuid.UUID | None,
    search: str | None,
    limit: int,
) -> list[tuple[uuid.UUID, str, str, int]]:
    """Who may be assigned: members of `group_id` (or anyone) who can work on the type.

    Each with their number of open records of the type (REQ-INC-053 AC2).
    """
    if not subject.holds(wtype.permission("assign")) and not subject.holds(
        wtype.permission("take")
    ):
        raise PermissionDenied(
            params={"permission": wtype.permission("assign"), "reason": NO_PERMISSION}
        )
    found = await holders.holders(
        session, subject.tenant_id, wtype.permission("edit"), search=search, limit=200
    )
    if group_id is not None:
        members = set(await session.scalars(users_in_groups(frozenset({group_id}))))
        found = [(u, n) for u, n in found if u in members]
    found = found[:limit]
    ids = [u for u, _ in found]
    loads: dict[uuid.UUID, int] = {}
    if ids:
        rows = await session.execute(
            select(WorkItem.technician_id, func.count())
            .where(
                WorkItem.type == wtype.code,
                WorkItem.deleted_at.is_(None),
                WorkItem.technician_id.in_(ids),
                _open(),
            )
            .group_by(WorkItem.technician_id)
        )
        loads = {row[0]: int(row[1]) for row in rows if row[0] is not None}
    contacts = await user_contacts(session, [str(u) for u in ids])
    return [(u, n, contacts.get(str(u), (n, ""))[1], loads.get(u, 0)) for u, n in found]


# --- validation -----------------------------------------------------------------------------------


@dataclass
class Draft:
    """Checked values of a create or an edit (only those sent, for edits)."""

    values: dict[str, Any]
    priority_reason: str | None = None


async def _check_people(session: AsyncSession, values: Mapping[str, Any]) -> list[tuple[str, str]]:
    wanted = {
        name: values[name]
        for name in ("requester_id", "on_behalf_of_id")
        if values.get(name) is not None
    }
    if not wanted:
        return []
    found = await user_names(session, [str(v) for v in wanted.values()])
    return [(name, "user_not_found") for name, value in wanted.items() if str(value) not in found]


async def _check_category(
    session: AsyncSession,
    wtype: WorkItemType,
    category_id: uuid.UUID | None,
    *,
    current: uuid.UUID | None,
) -> list[tuple[str, str]]:
    if category_id is None or category_id == current:
        return []
    node = await session.scalar(
        select(WorkItemCategory).where(
            WorkItemCategory.id == category_id,
            WorkItemCategory.type == wtype.code,
            WorkItemCategory.deleted_at.is_(None),
        )
    )
    if node is None:
        return [("category_id", "category_not_found")]
    if node.disabled_at is not None:
        return [("category_id", "category_disabled")]
    return []


async def _check_units(session: AsyncSession, values: Mapping[str, Any]) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    kinds: tuple[tuple[str, Literal["site", "group"]], ...] = (
        ("site_id", "site"),
        ("group_id", "group"),
    )
    for name, kind in kinds:
        value = values.get(name)
        if value is not None and value not in await existing_unit_ids(session, kind, [value]):
            problems.append((name, f"{name.removesuffix('_id')}_not_found"))
    department = values.get("department_id")
    if department is not None and department not in await existing_departments(
        session, [department]
    ):
        problems.append(("department_id", "department_not_found"))
    return problems


def _check_fields(  # noqa: C901, PLR0912 - one rule per field, flat
    values: Mapping[str, Any], *, creating: bool
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Pure field rules; returns the cleaned values and (field, code) problems."""
    cleaned: dict[str, Any] = {}
    problems: list[tuple[str, str]] = []
    if creating or "subject" in values:
        subject, codes = clean_subject(str(values.get("subject") or ""))
        problems += [("subject", c) for c in codes]
        cleaned["subject"] = subject
    if "description" in values:
        raw = values["description"]
        if raw is None or is_blank(str(raw)):
            cleaned["description"] = None
        else:
            html = sanitize_html(str(raw))
            if len(html) > DESCRIPTION_MAX:
                problems.append(("description", "value_too_long"))
            cleaned["description"] = None if is_blank(html) else html
    for name in ANALYSIS_FIELDS:  # problems' analysis (WP-044b): rich text like the description
        if name in values:
            raw = values[name]
            html = "" if raw is None or is_blank(str(raw)) else sanitize_html(str(raw))
            if len(html) > DESCRIPTION_MAX:
                problems.append((name, "value_too_long"))
            cleaned[name] = None if is_blank(html) else html
    if creating and values.get("requester_id") is None:
        problems.append(("requester_id", "required"))
    for name in ("requester_id", "on_behalf_of_id", "site_id", "department_id", "category_id"):
        if name in values:
            if name == "requester_id" and values[name] is None:
                problems.append(("requester_id", "required"))
            cleaned[name] = values[name]
    for name, enum in (("impact", Impact), ("urgency", Urgency)):
        if name in values:
            value = values[name]
            if value is not None and value not in set(enum):
                problems.append((name, "invalid_choice"))
            cleaned[name] = value
    if "impact_details" in values:
        details, codes = clean_impact_details(values["impact_details"])
        problems += [("impact_details", c) for c in codes]
        cleaned["impact_details"] = details
    if "level" in values:
        cleaned["level"] = values["level"] or None
    for name in PROBLEM_FIELDS:
        if name in values:
            cleaned[name] = values[name] or None
    if "tags" in values:
        tags, codes = clean_tags(list(values["tags"] or []))
        problems += [("tags", c) for c in codes]
        cleaned["tags"] = tags
    if "channel" in values:
        problems += [("channel", c) for c in channel_problems(values["channel"])]
        cleaned["channel"] = values["channel"]
    return cleaned, problems


def _priority_input(
    values: Mapping[str, Any],
) -> tuple[str | None, str | None, list[tuple[str, str]]]:
    """(manual priority or None, reason, problems) when `priority` was sent."""
    priority = values.get("priority")
    reason = (values.get("priority_reason") or "").strip() or None
    problems: list[tuple[str, str]] = []
    if priority is not None and priority not in set(Priority):
        problems.append(("priority", "invalid_choice"))
    if priority is not None and reason is None:
        problems.append(("priority_reason", "required"))
    if reason is not None and len(reason) > PRIORITY_REASON_MAX:
        problems.append(("priority_reason", "value_too_long"))
    return priority, reason, problems


async def _check_assignment(  # noqa: PLR0913 - the assignment and who makes it, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    holders: PermissionHolders,
    *,
    group_id: uuid.UUID | None,
    technician_id: uuid.UUID | None,
) -> list[tuple[str, str]]:
    problems = await _check_units(session, {"group_id": group_id})
    if problems or technician_id is None:
        return problems
    if not await holders.user_holds(
        session, subject.tenant_id, technician_id, wtype.permission("edit")
    ):
        return [("technician_id", "technician_not_allowed")]
    if group_id is not None and not subject.holds(wtype.permission("assign_outside_group")):
        members = set(await session.scalars(users_in_groups(frozenset({group_id}))))
        if technician_id not in members:
            return [("technician_id", "technician_not_in_group")]
    return []


# --- writing helpers ------------------------------------------------------------------------------


def _json(value: Any) -> Any:  # noqa: ANN401 - field values of several types
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, list):
        return [str(v) for v in value]
    return value


# A problem's own fields (WP-044a s2, REQ-PRB-005, -006): codes from its pick lists, the outage.
PROBLEM_FIELDS = ("problem_type", "root_cause_category", "outage_started_at", "outage_ended_at")
# The analysis (WP-044b, REQ-PRB-030): changing it needs problems.edit_analysis; the root cause
# is read only with problems.view_root_cause (D-140 Q7).
# A list, not a pair: the field-problem scanner reads two-string tuples as (field, code).
# The workaround (s3, REQ-PRB-034) is the solution: its own right, and seen by everyone who
# sees the problem (D-140 Q7), so it is never hidden.
ANALYSIS_FIELDS = ["root_cause", "symptoms", "workaround"]
HIDDEN_WITHOUT = {"root_cause": "view_root_cause"}
EDITED_WITH = {"workaround": "edit_solution"}  # otherwise edit_analysis
_PROBLEM_LISTS = {"problem_type": PickList.PROBLEM_TYPE, "root_cause_category": PickList.ROOT_CAUSE}


def _analysis_rights(names: Sequence[str]) -> set[str]:
    """The rights changing these fields needs: its edit right, and reading it when hidden."""
    rights = {EDITED_WITH.get(n, "edit_analysis") for n in names}
    return rights | {HIDDEN_WITHOUT[n] for n in names if n in HIDDEN_WITHOUT}


async def _may_change_analysis(
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record: WorkItem,
    names: Sequence[str],
) -> None:
    """Changing the analysis needs edit_analysis; the root cause also needs to be readable."""
    changing = [n for n in names if wtype.code is WorkItemTypeCode.PROBLEM]
    if not changing:
        return
    actions = _analysis_rights(changing)
    for action in sorted(actions):
        if not await _may(session, subject, wtype, action, record.id):
            raise PermissionDenied(
                params={"permission": wtype.permission(action), "reason": NO_PERMISSION}
            )


def _may_give_analysis(subject: Subject, wtype: WorkItemType, cleaned: dict[str, Any]) -> None:
    """On the create form (REQ-PRB-018 AC1): the same rights as changing it later."""
    given = [n for n in ANALYSIS_FIELDS if cleaned.get(n) is not None]
    if not given or wtype.code is not WorkItemTypeCode.PROBLEM:
        return
    actions = _analysis_rights(given)
    for action in sorted(actions):
        if not subject.holds(wtype.permission(action)):
            raise PermissionDenied(
                params={"permission": wtype.permission(action), "reason": NO_PERMISSION}
            )


@dataclass(frozen=True)
class AnalysisChange:
    """The last change of one analysis field."""

    field: str
    actor_id: str | None  # a user ID, or None for the system
    at: datetime


async def _analysis_changes(
    session: AsyncSession, record_id: uuid.UUID, hidden: frozenset[str]
) -> tuple[AnalysisChange, ...]:
    """The latest change per analysis field the subject may read (one query, DISTINCT ON)."""
    shown = [n for n in ANALYSIS_FIELDS if n not in hidden]
    if not shown:
        return ()
    rows = await session.execute(
        select(
            FieldChange.field, FieldChange.actor_type, FieldChange.actor_id, FieldChange.occurred_at
        )
        .where(
            FieldChange.record_type == RECORD_TYPE,
            FieldChange.record_id == record_id,
            FieldChange.field.in_(shown),
        )
        .order_by(FieldChange.field, FieldChange.occurred_at.desc())
        .ext(distinct_on(FieldChange.field))
    )
    return tuple(
        AnalysisChange(
            field=name,
            actor_id=actor if actor_type == "user" and actor and _is_uuid(actor) else None,
            at=at,
        )
        for name, actor_type, actor, at in rows
    )


async def hidden_fields(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> frozenset[str]:
    """Fields of the record the subject may not read (the root cause, D-140 Q7)."""
    if wtype.code is not WorkItemTypeCode.PROBLEM:
        return frozenset()
    hidden: set[str] = set()
    for name, action in HIDDEN_WITHOUT.items():
        if not await _may(session, subject, wtype, action, record_id):
            hidden.add(name)
    return frozenset(hidden)


def _check_problem_fields(
    wtype: WorkItemType,
    cat: Catalogue,
    cleaned: Mapping[str, Any],
    record: WorkItem | None,
) -> list[tuple[str, str]]:
    """The problem fields' problems, by field.

    Only on problems; codes offered (a record's retired one may stay); the outage ends at or after
    it begins.
    """
    given = [name for name in (*PROBLEM_FIELDS, *ANALYSIS_FIELDS) if name in cleaned]
    if wtype.code is not WorkItemTypeCode.PROBLEM:
        return [(name, "not_allowed") for name in given if cleaned[name] is not None]
    found: list[tuple[str, str]] = []
    for name, pick in _PROBLEM_LISTS.items():
        value = cleaned.get(name)
        current = getattr(record, name) if record is not None else None
        if (
            name in cleaned
            and value is not None
            and value != current
            and value not in cat.reason_codes(pick)
        ):
            found.append((name, "invalid_choice"))
    start = cleaned.get("outage_started_at", record.outage_started_at if record else None)
    end = cleaned.get("outage_ended_at", record.outage_ended_at if record else None)
    if start is not None and end is not None and end < start:
        found.append(("outage_ended_at", "before_start"))
    return found


def _check_level(
    cat: Catalogue, level: str | None, *, current: str | None
) -> list[tuple[str, str]]:
    """A level offered for new input; the record's own (perhaps retired) level may stay."""
    if level is None or level == current or level in cat.reason_codes(PickList.LEVEL):
        return []
    return [("level", "invalid_choice")]


PROBLEM_FIELDS_SNAPSHOT = (
    "problem_type",
    "root_cause_category",
    "outage_started_at",
    "outage_ended_at",
    *ANALYSIS_FIELDS,
)
SNAPSHOT_FIELDS = (
    "subject",
    "description",
    "requester_id",
    "on_behalf_of_id",
    "channel",
    "site_id",
    "department_id",
    "group_id",
    "technician_id",
    "category_id",
    "impact",
    "impact_details",
    "urgency",
    "priority",
    "priority_source",
    "level",
    *PROBLEM_FIELDS_SNAPSHOT,
    "tags",
    "status",
    "template_id",
)


def _snapshot(record: WorkItem, names: Sequence[str] = SNAPSHOT_FIELDS) -> dict[str, Any]:
    snapshot = {name: _json(getattr(record, name)) for name in names}
    if names is SNAPSHOT_FIELDS:
        # Custom fields as `custom.<key>`: history and events name each one (WP-026).
        snapshot |= {f"custom.{key}": value for key, value in (record.custom or {}).items()}
    return snapshot


async def _custom_text(
    session: AsyncSession,
    wtype: WorkItemType,
    custom: Mapping[str, Any],
    record_id: uuid.UUID | None = None,
) -> str | None:
    """Free text kept on the record for search (WP-026, WP-027).

    Custom values, and a release's version and build reference (REQ-REL-005 AC1).
    """
    parts = [await metadata.text_for_search(session, wtype.code.value, custom) if custom else None]
    if record_id is not None and wtype.code is WorkItemTypeCode.RELEASE:
        details = await session.get(WorkItemReleaseDetails, (config.tenant_of(session), record_id))
        if details is not None:
            parts.append(release_rules.search_terms(_detail_values(details)))
    text = " ".join(p for p in parts if p)
    return text or None


def _is_uuid(value: Any) -> bool:  # noqa: ANN401 - a JSON value
    """A custom value naming a person (only person fields hold UUIDs)."""
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _flat(custom: Mapping[str, Any]) -> dict[str, Any]:
    return {f"custom.{key}": value for key, value in custom.items()}


async def _custom_in(
    session: AsyncSession,
    wtype: WorkItemType,
    values: Mapping[str, Any],
    *,
    current: Mapping[str, Any] | None,
    creating: bool,
) -> tuple[dict[str, Any] | None, list[tuple[str, str]]]:
    """The record's custom values after this write (None: unchanged), and problems (WP-026)."""
    if "custom" not in values and not creating:
        return None, []
    sent = values.get("custom") or {}
    if not isinstance(sent, Mapping):
        return None, [("custom", "invalid_value")]
    if wtype.code.value not in set(metadata.CustomFieldEntity):
        return (None, [("custom", "not_allowed")]) if sent else (None, [])
    cleaned, problems = await metadata.clean(
        session, wtype.code.value, sent, current=current, creating=creating, defaults=creating
    )
    merged = {**(current or {}), **cleaned}
    return {k: v for k, v in merged.items() if v is not None}, problems


async def _value_errors(
    session: AsyncSession, wtype: WorkItemType, problems: Sequence[tuple[str, str]]
) -> ValidationFailed:
    """The 422, with the limit each custom value problem names ("Maximum is 1000.5")."""
    custom = [p for p in problems if is_custom(p[0])]
    params = (
        await metadata.problem_params(session, wtype.code.value, custom)
        if custom and wtype.code.value in set(metadata.CustomFieldEntity)
        else {}
    )
    return _errors(problems, **params)


def _audience(record: WorkItem) -> Audience:
    return Audience(
        group_id=record.group_id,
        site_id=record.site_id,
        technician_id=record.technician_id,
        unassigned=record.group_id is None and record.technician_id is None,
    )


async def _conflict(session: AsyncSession, error: Conflict, record_id: uuid.UUID) -> Conflict:
    return await explain_conflict(
        session,
        error,
        record_type=RECORD_TYPE,
        record_id=record_id,
        names=lambda ids: display_names(session, ids),
    )


async def _update(
    session: AsyncSession, record: WorkItem, expected_version: int, changes: Mapping[str, Any]
) -> WorkItem:
    """Every versioned save of a work item; the SLA clock runs in the same save (WP-025)."""
    if record.version != expected_version:
        raise await _conflict(session, _stale(record, expected_version), record.id)
    before = {k: getattr(record, k) for k in sla_glue.STAMP_COLUMNS}
    stamped = await sla_glue.sla_columns(session, record, changes, now=_now())
    try:
        updated = await WorkItemRepository(session).update(
            record.id, expected_version=expected_version, changes={**changes, **stamped}
        )
    except Conflict as error:
        raise await _conflict(session, error, record.id) from error
    await sla_glue.record_sla_history(session, updated, before, stamped)
    return updated


async def stale_record(session: AsyncSession, record: WorkItem, expected_version: int) -> Conflict:
    """The 409 for a save at an old version, saying who changed what since (§5g)."""
    return await _conflict(session, _stale(record, expected_version), record.id)


def _stale(record: WorkItem, expected_version: int) -> Conflict:
    return Conflict(
        code="version_conflict",
        params={"expected_version": expected_version, "current_version": record.version},
    )


# What a write did to the writer's own reach (D-053, D-068).
KEPT = "kept"  # they still see it through their scope
FOLLOWING = "following"  # it left their scope; they keep following it with access
LOST = "lost"  # it left their scope and they chose not to follow it


async def _keep_in_reach(  # noqa: PLR0913 - the record, the writer and their two choices, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record: WorkItem,
    *,
    confirmed: bool,
    keep_following: bool | None,
) -> str:
    """After a write: check the record is still visible to the writer (D-053, D-068).

    Not visible and not confirmed: 409 `would_lose_access` with the tenant's "keep following"
    default (the transaction rolls back; the UI asks and resends with `confirm_lose_access` and
    `keep_following`). Confirmed: FOLLOWING when they keep following (the default, D-068; the
    caller adds the follower after its own history), else LOST.
    """
    if await _may(session, subject, wtype, "view", record.id):
        return KEPT
    cat = await config.load(session, wtype)
    if not confirmed:
        raise Conflict(
            code="would_lose_access",
            params={
                "display_id": record.display_id,
                "keep_following": cat.keep_following_on_handover,
            },
        )
    keep = cat.keep_following_on_handover if keep_following is None else keep_following
    return FOLLOWING if keep else LOST


async def _follow_after_handover(
    session: AsyncSession, subject: Subject, record: WorkItem, reach: str, source: Source
) -> None:
    if reach == FOLLOWING:
        await followers.follow(
            session,
            record,
            subject.user_id,
            reason=FollowReason.HANDED_OVER,
            grants_access=True,
            source=source,
        )


async def _status_change(  # noqa: PLR0913 - the record, the move and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    record: WorkItem,
    action: WorkItemAction,
    *,
    target: str,
    reason_code: str | None,
    reason_text: str | None,
) -> dict[str, Any]:
    """Column changes of a status move: category, reason, pause clock and time stamps."""
    cat = await config.load(session, wtype)
    old = StatusCategory(record.status_category)
    new = cat.lifecycle.category(target)
    now = _now()
    clock = move_pause_clock(
        PauseClock(record.paused_since, record.paused_seconds), old=old, new=new, now=now
    )
    changes: dict[str, Any] = {
        "status": target,
        "status_category": new,
        "status_changed_at": now,
        "status_reason_code": reason_code,
        "status_reason_text": reason_text,
        "paused_since": clock.paused_since,
        "paused_seconds": clock.paused_seconds,
    }
    if action == WorkItemAction.CANCEL:
        changes["status_before_cancel"] = record.status
    if action == WorkItemAction.UNDO_CANCEL:
        changes["status_before_cancel"] = None
    # Appendix A (problems): on hold returns to where it was put on hold (WP-044a).
    if action == WorkItemAction.HOLD:
        changes["status_before_pause"] = record.status
    if action == WorkItemAction.RESUME:
        changes["status_before_pause"] = None
    if new == StatusCategory.RESOLVED:
        changes["resolved_at"] = now
    if new == StatusCategory.CLOSED:
        changes["closed_at"] = now
        if record.resolved_at is None:
            changes["resolved_at"] = now
    if action == WorkItemAction.REOPEN:
        changes |= {
            "reopen_count": record.reopen_count + 1,
            "last_reopened_at": now,
            "resolved_at": None,
            "closed_at": None,
        }
    return changes


STAMP_FIELDS = (
    "status",
    "status_reason_code",
    "resolved_at",
    "closed_at",
    "reopen_count",
    "last_reopened_at",
    # WP-020f: the fix and the closure code; history keeps them after a reopen (REQ-INC-097).
    "resolution",
    "closure_code",
)


async def _record_status(  # noqa: PLR0913 - the move, its reason and its source, explicit
    session: AsyncSession,
    before: Mapping[str, Any],
    record: WorkItem,
    action: WorkItemAction,
    *,
    source: Source,
    reason: str | None,
    automatic: bool,
    extra: Sequence[Change] = (),
    rule: str = "assignment",
) -> None:
    after = _snapshot(record, STAMP_FIELDS)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="status",
        changes=[Change(n, before[n], v) for n, v in after.items() if before[n] != v] + list(extra),
        source=source,
        reason=reason,
        automation_ref={"kind": "auto_move", "rule": rule, "action": action} if automatic else None,
    )
    await record_event(
        session,
        WorkItemStatusChanged(
            work_item_id=record.id,
            type=record.type,
            display_id=record.display_id,
            status=record.status,
            status_category=record.status_category,
            action=action,
            from_status=str(before["status"]),
            to_status=record.status,
            automatic=automatic,
        ),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )


def _closed(record: WorkItem) -> bool:
    return StatusCategory(record.status_category) in FINAL_CATEGORIES


# --- create ---------------------------------------------------------------------------------------

# What business rules see of a new record's input (with group, technician, priority and custom
# fields added by the caller), and which of those are IDs.
RULE_INPUTS = (
    "subject",
    "description",
    "requester_id",
    "on_behalf_of_id",
    "site_id",
    "department_id",
    "category_id",
    "impact",
    "urgency",
    "level",
    "tags",
)
_REFERENCE_INPUTS = frozenset(
    {"requester_id", "on_behalf_of_id", "site_id", "department_id", "category_id"}
)


def _first_priority(
    cat: Catalogue, cleaned: Mapping[str, Any], manual: str | None, rules: Mapping[str, Any]
) -> tuple[str, PrioritySource]:
    """A rule's priority, else the person's (with a reason), else the matrix (REQ-RUL-006)."""
    if "priority" in rules:
        return rules["priority"], PrioritySource.RULE
    if manual is not None:
        return manual, PrioritySource.MANUAL
    computed = compute_priority(
        cleaned.get("impact"), cleaned.get("urgency"), cat.matrix, cat.default_priority
    )
    return computed.priority, computed.source


def _apply_automated(
    values: Mapping[str, Any],
    cleaned: dict[str, Any],
    custom: dict[str, Any] | None,
    group_id: uuid.UUID | None,
    technician_id: uuid.UUID | None,
) -> tuple[dict[str, Any] | None, uuid.UUID | None, uuid.UUID | None]:
    """Automated snapshot values back into a new record's typed inputs (priority aside)."""
    for name, value in values.items():
        if name.startswith("custom."):
            custom = {**(custom or {}), name.removeprefix("custom."): value}
        elif name == "group_id":
            group_id = uuid.UUID(value) if value else None
        elif name == "technician_id":
            technician_id = uuid.UUID(value) if value else None
        elif name in _REFERENCE_INPUTS:
            cleaned[name] = uuid.UUID(value) if value else None
        elif name != "priority":
            cleaned[name] = value
    return custom, group_id, technician_id


async def _rules_on_edit(
    session: AsyncSession,
    wtype: WorkItemType,
    record: WorkItem,
    columns: dict[str, Any],
    eligible: "automation.EligibleProvider | None" = None,
) -> "automation.Automated":
    """Run the rules on an edit and fold their values into `columns` (typed, custom merged).

    With `eligible`, a move to another group without a technician is auto-assigned inside
    that group afterwards (REQ-ASG-001 "on move"), never outside it.
    """
    facts = await automation.requester_facts(session, record.requester_id)
    before = {**_snapshot(record), **automation.flat_custom(record.custom), **facts}
    edited = {
        name: _json(value)
        for name, value in columns.items()
        if name not in {"custom", "custom_text"}
    }
    if "custom" in columns:
        current_custom = automation.flat_custom(record.custom)
        edited |= dict.fromkeys(current_custom)
        edited |= automation.flat_custom(columns["custom"])
    automated = await automation.automate(
        session,
        wtype,
        event=RuleEvent.UPDATE,
        record_id=record.id,
        before=before,
        after={**before, **edited},
        eligible=eligible,
        route=False,
        assign_moment="move" if eligible is not None else None,
    )
    custom_changes: dict[str, Any] = {}
    for name, value in automated.values.items():
        if name.startswith("custom."):
            custom_changes[name.removeprefix("custom.")] = value
        elif name in _REFERENCE_INPUTS or name in {"group_id", "technician_id"}:
            columns[name] = uuid.UUID(value) if value else None
        else:
            columns[name] = value
    if "priority" in automated.values:
        columns["priority_source"] = PrioritySource.RULE
    if custom_changes:
        merged = {**(columns.get("custom", record.custom) or {}), **custom_changes}
        columns["custom"] = {k: v for k, v in merged.items() if v is not None}
        columns["custom_text"] = await _custom_text(session, wtype, columns["custom"], record.id)
    return automated


async def _eligible(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, holders: PermissionHolders
) -> list[uuid.UUID]:
    """Who may work the type (auto-assignment then keeps the group's members only)."""
    found = await holders.holders(session, subject.tenant_id, wtype.permission("edit"), limit=500)
    return [user_id for user_id, _name in found]


async def _record_automation(
    session: AsyncSession, record: WorkItem, automated: automation.Automated
) -> None:
    """One history entry per rule, routing and assignment step, and the run log (REQ-WI-004)."""
    for ref, changes in automated.entries:
        await record_changes(
            session,
            record_type=RECORD_TYPE,
            record_id=record.id,
            version=record.version,
            kind="updated",
            changes=[Change(name, old, new) for name, old, new in changes],
            source="rule",
            automation_ref=ref,
        )
    await log_trace(session, record.type, record.id, automated.trace)


async def _place(session: AsyncSession, cleaned: dict[str, Any]) -> None:
    """Site and department from the requester unless sent (REQ-INC-016 AC1, WP-021).

    Their profile first, then (site) the one site they belong to.
    """
    placement = await person_placement(session, cleaned["requester_id"])
    if "site_id" not in cleaned and placement.site_id is not None:
        cleaned["site_id"] = placement.site_id
    if "department_id" not in cleaned and placement.department_id is not None:
        cleaned["department_id"] = placement.department_id
    if cleaned.get("site_id") is None:
        sites = (await memberships(session, cleaned["requester_id"])).site_ids
        if len(sites) == 1:
            cleaned["site_id"] = next(iter(sites))


async def _request_item(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, values: Mapping[str, Any]
) -> service_catalog.RequestItem | None:
    """The catalog item of a new service request (refused without one); None for other types."""
    given = values.get("catalog_item_id")
    if wtype.code is not WorkItemTypeCode.SERVICE_REQUEST:
        if given is not None or values.get("answers"):
            raise ValidationFailed(
                errors=[
                    FieldError(
                        field="body.catalog_item_id",
                        code="not_allowed",
                        message_key="errors.field.not_allowed",
                    )
                ]
            )
        return None
    if not given:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.catalog_item_id",
                    code="required",
                    message_key="errors.field.required",
                )
            ]
        )
    try:
        return await service_catalog.request_item(
            session, subject, uuid.UUID(str(given)), values.get("answers") or {}
        )
    except NotFound as error:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.catalog_item_id",
                    code="catalog_item_not_found",
                    message_key="errors.field.catalog_item_not_found",
                )
            ]
        ) from error


def _started(item: service_catalog.RequestItem | None, cat: Catalogue) -> sr_rules.Start | None:
    """How a service request starts from its item (None for other types)."""
    if item is None:
        return None
    return sr_rules.start(
        sr_rules.ItemDecides(
            needs_approval=item.needs_approval,
            default_priority=item.default_priority,
            group_id=item.group_id,
            technician_id=item.technician_id,
            technician_after_approval=item.technician_after_approval,
        ),
        tenant_default_priority=cat.default_priority,
    )


def _from_item(
    started: sr_rules.Start | None,
    initial: str,
    group_id: uuid.UUID | None,
    technician_id: uuid.UUID | None,
) -> tuple[str, uuid.UUID | None, uuid.UUID | None]:
    """The first status and assignment: the item's, where the person set none."""
    if started is None:
        return initial, group_id, technician_id
    return started.status, group_id or started.group_id, technician_id or started.technician_id


def _item_priority(
    started: sr_rules.Start | None, priority: str, source: PrioritySource
) -> tuple[str, PrioritySource]:
    """A rule's or the person's priority stays; else the item's default (REQ-SR-005)."""
    if started is None or not started.priority_from_item:
        return priority, source
    if source in {PrioritySource.RULE, PrioritySource.MANUAL}:
        return priority, source
    return started.priority, PrioritySource.CATALOG_ITEM


def _item_columns(
    item: service_catalog.RequestItem | None, values: Mapping[str, Any]
) -> dict[str, Any]:
    """A service request's own columns (incidents keep their defaults)."""
    if item is None:
        return {}
    status = (
        sr_rules.ApprovalStatus.PENDING
        if item.needs_approval
        else sr_rules.ApprovalStatus.NOT_NEEDED
    )
    return {
        "catalog_item_id": item.item_id,
        "answers": dict(values.get("answers") or {}),
        "approval_status": status.value,
        "sla_counts_approval": item.needs_approval and item.count_approval_time,
        "item_sla_policy_id": item.sla_policy_id,
    }


def _person_facts(user_id: uuid.UUID, placement: Placement) -> sr_rules.PersonFacts:
    return sr_rules.PersonFacts(
        user_id=user_id,
        department_id=placement.department_id,
        site_id=placement.site_id,
        is_requester=placement.user_type == "requester",
        manager_id=placement.manager_id,
        active=placement.active,
        can_sign_in=placement.can_sign_in,
        is_service=placement.user_type == "service",
    )


async def may_raise_for_people(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, candidates: Sequence[uuid.UUID]
) -> list[uuid.UUID]:
    """Of `candidates`, those the subject may raise a record for (REQ-SR-011), in order.

    The same rule as creation: the tenant's on-behalf scope, their own direct reports always,
    never a deactivated person or a service identity; never the subject themselves (the portal
    form offers "myself" on its own).
    """
    cat = await config.load(session, wtype)
    scope = sr_rules.OnBehalfScope(cat.on_behalf_scope)
    me = _person_facts(subject.user_id, await person_placement(session, subject.user_id))
    found: list[uuid.UUID] = []
    for person in candidates:
        if person == subject.user_id:
            continue
        theirs = _person_facts(person, await person_placement(session, person))
        if sr_rules.may_raise_for(scope, me, theirs):
            found.append(person)
    return found


async def _on_behalf_problems(
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    cat: Catalogue,
    cleaned: Mapping[str, Any],
) -> None:
    """A requester raising a record for someone else stays within the tenant's scope (REQ-SR-011).

    Staff (who may assign records) raise for anyone; a requester for themselves, their direct
    reports, and the people the scope allows; anyone else is refused with 403 (AC1).
    """
    target = cleaned.get("on_behalf_of_id")
    if target is None or subject.holds(wtype.permission("assign")):
        return
    if cleaned.get("requester_id") != subject.user_id:
        return  # raising as someone else needs staff rights, checked with the requester
    mine, theirs = (
        await person_placement(session, subject.user_id),
        await person_placement(session, target),
    )
    if not sr_rules.may_raise_for(
        sr_rules.OnBehalfScope(cat.on_behalf_scope),
        _person_facts(subject.user_id, mine),
        _person_facts(target, theirs),
    ):
        raise PermissionDenied(code="on_behalf_out_of_scope")


async def _first_stage(session: AsyncSession, wtype: WorkItemType) -> dict[str, Any]:
    """Stage columns and first status of a new staged record ({} for other types)."""
    if wtype.stages is None:
        return {}
    model = await stage_service.load_model(session, wtype)
    return stage_service.first_columns(model, DEFAULT_PATH)


def _initial(cat: Catalogue, stage_columns: dict[str, Any]) -> str:
    """The first status: a staged type's first stage's, else the first status a person can set."""
    staged_first = stage_columns.pop("status", None)
    if staged_first is not None:
        return str(staged_first)
    return next(s.code for s in cat.statuses if not s.system and not s.disabled)


async def create(  # noqa: PLR0913, PLR0915 - the new record's inputs and checks, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    values: Mapping[str, Any],
    *,
    source: Source,
    holders: PermissionHolders,
    channel: Channel | None = None,
    entry_group_id: uuid.UUID | None = None,
) -> WorkItemView:
    """A new record in the life cycle's first status (or `assigned` when a technician is set).

    `channel` and `entry_group_id` are for entry points (e-mail WP-024, the portal WP-028),
    never a client: the channel the record came in by (e-mail is otherwise reserved), and that
    entry point's group, which routing applies after its rules and before the category's
    group (history: "routed to the group of the way it came in").
    """
    cat = await config.load(session, wtype)
    cleaned, problems = _check_fields(values, creating=True)
    manual, priority_reason, priority_problems = _priority_input(values)
    problems += priority_problems
    if manual is not None and not subject.holds(wtype.permission("change_priority")):
        raise PermissionDenied(
            params={"permission": wtype.permission("change_priority"), "reason": NO_PERMISSION}
        )
    group_id = values.get("group_id")
    technician_id = values.get("technician_id")
    if (group_id or technician_id) and not subject.holds(wtype.permission("assign")):
        raise PermissionDenied(
            params={"permission": wtype.permission("assign"), "reason": NO_PERMISSION}
        )
    custom, custom_problems = await _custom_in(session, wtype, values, current=None, creating=True)
    problems += custom_problems
    # A service request comes from its catalog item (REQ-SR-001 AC2), which decides its first
    # status, priority and assignment (REQ-SR-005, -008, -021); the person's own choices of
    # group and technician were checked above, the item's were checked when it was saved.
    item = await _request_item(session, subject, wtype, values)
    started = _started(item, cat)
    problems += [] if item is None else list(item.answer_problems)
    template = await templates.for_create(session, wtype, values.get("template_id"))
    problems += await templates.required_problems(
        session, wtype, template, {**values, **cleaned, **_flat(custom or {})}
    )
    problems += _check_level(cat, cleaned.get("level"), current=None)
    problems += _check_problem_fields(wtype, cat, cleaned, None)
    if problems:
        raise await _value_errors(session, wtype, problems)
    _may_give_analysis(subject, wtype, cleaned)
    problems += await _check_people(session, cleaned)
    await _on_behalf_problems(session, subject, wtype, cat, cleaned)
    problems += await _check_units(
        session,
        {"site_id": cleaned.get("site_id"), "department_id": cleaned.get("department_id")},
    )
    problems += await _check_category(session, wtype, cleaned.get("category_id"), current=None)
    problems += await _check_assignment(
        session, subject, wtype, holders, group_id=group_id, technician_id=technician_id
    )
    if problems:
        raise await _value_errors(session, wtype, problems)
    await _place(session, cleaned)
    # A staged type starts in its path's first stage and that stage's first status (ADR-041).
    stage_columns = await _first_stage(session, wtype)
    initial, group_id, technician_id = _from_item(
        started,
        _initial(cat, stage_columns),
        group_id,
        technician_id,
    )
    channel_given = channel
    channel = (
        channel or cleaned.get("channel") or (Channel.PHONE if source == "ui" else Channel.API)
    )
    # Automation in the documented order (REQ-RUL-006): business rules, the matrix, routing and
    # auto-assignment. What the person entered stays their history; each automated change is
    # its own entry naming the rule, the routing reason or the assignment method.
    record_id = new_id()
    entered = {
        **{name: _json(cleaned.get(name)) for name in RULE_INPUTS},
        "group_id": _json(group_id),
        "technician_id": _json(technician_id),
        "priority": manual,
        "channel": channel,
        "status": initial,
        "status_category": cat.lifecycle.category(initial),
        "template_id": str(template.id),
        **automation.flat_custom(custom),
        **await automation.requester_facts(session, cleaned["requester_id"]),
    }
    automated = await automation.automate(
        session,
        wtype,
        event=RuleEvent.CREATE,
        record_id=record_id,
        before=None,
        after=entered,
        eligible=lambda: _eligible(session, subject, wtype, holders),
        route=True,
        assign_moment="create",
        entry_group_id=entry_group_id,
    )
    custom, group_id, technician_id = _apply_automated(
        automated.values, cleaned, custom, group_id, technician_id
    )
    priority, priority_source = _item_priority(
        started, *_first_priority(cat, cleaned, manual, automated.values)
    )
    now = _now()
    number = await next_display_number(session, wtype.counter_key)
    record = WorkItem(
        id=record_id,
        type=wtype.code,
        display_number=number,
        display_id=f"{cat.prefix}-{number}",
        subject=cleaned["subject"],
        description=cleaned.get("description"),
        requester_id=cleaned["requester_id"],
        on_behalf_of_id=cleaned.get("on_behalf_of_id"),
        channel=channel,
        site_id=cleaned.get("site_id"),
        department_id=cleaned.get("department_id"),
        desk_id=await default_desk_id(session),
        group_id=group_id,
        technician_id=technician_id,
        category_id=cleaned.get("category_id"),
        impact=cleaned.get("impact"),
        impact_details=cleaned.get("impact_details"),
        urgency=cleaned.get("urgency"),
        priority=priority,
        priority_source=priority_source,
        level=cleaned.get("level"),
        **{name: cleaned.get(name) for name in (*PROBLEM_FIELDS, *ANALYSIS_FIELDS)},
        template_id=template.id,
        # The template's transition set, if the type has it (WP-044a s4, REQ-PRB-025).
        lifecycle=template.lifecycle
        if template.lifecycle in cat.lifecycles
        else STANDARD_LIFECYCLE,
        **_item_columns(item, values),
        custom=custom or {},
        custom_text=await _custom_text(session, wtype, custom or {}),
        status=initial,
        status_category=cat.lifecycle.category(initial),
        status_changed_at=now,
        tags=cleaned.get("tags", []),
        first_assigned_at=now if technician_id else None,
        paused_seconds=0,
        reopen_count=0,
        reassignment_count=0,
        **stage_columns,
    )
    await WorkItemRepository(session).add(record)
    stamped = await sla_glue.sla_columns(session, record, None, now=now)
    for name, value in stamped.items():  # the same insert: the record is still at version 1
        setattr(record, name, value)
    await session.flush()
    await stage_service.start(session, record, now=now)
    if custom:
        await metadata.mark_used(session, wtype.code.value, list(custom))
    # An entry point (e-mail, the portal) creates as the requester, who never had console
    # access to lose and sees their own record as its requester: no hand-over question.
    entry_point = channel_given is not None
    reach = await _keep_in_reach(
        session,
        subject,
        wtype,
        record,
        confirmed=entry_point or bool(values.get("confirm_lose_access")),
        keep_following=False if entry_point else values.get("keep_following"),
    )
    handed_over = reach == LOST
    after = _snapshot(record)
    # The person's entry holds what they entered; automated values are named in their own entries.
    by_person = {
        name: (entered.get(name) if name in automated.values else value)
        for name, value in after.items()
    }
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="created",
        changes=[
            Change(name, None, value)
            for name, value in by_person.items()
            if value not in (None, [])
        ],
        source=source,
        reason=priority_reason,
    )
    await _record_automation(session, record, automated)
    await record_event(
        session,
        WorkItemCreated(
            work_item_id=record.id,
            type=record.type,
            display_id=record.display_id,
            status=record.status,
            status_category=record.status_category,
            technician_id=record.technician_id,
        ),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )
    await approval_stage.after_submission(session, record, item, source=source)  # REQ-SR-021
    if technician_id is not None and cat.auto_status_on_assign:
        move = after_assignment(
            cat.lifecycle_of(record.lifecycle),
            record.status,
            had_technician=False,
            has_technician=True,
        )
        if move is not None:
            before = _snapshot(record, STAMP_FIELDS)
            target = cat.lifecycle_of(record.lifecycle).target(
                record.status, move, before_cancel=None
            )
            changes = await _status_change(
                session, wtype, record, move, target=target, reason_code=None, reason_text=None
            )
            record = await _update(session, record, record.version, changes)
            await _record_status(
                session, before, record, move, source=source, reason=None, automatic=True
            )
    await _follow_after_handover(session, subject, record, reach, source)
    if handed_over:
        return WorkItemView(
            record=record, actions=[], operations=[], history_count=0, visible=False
        )
    return await _view(session, subject, wtype, record)


# --- edit -----------------------------------------------------------------------------------------


async def update(  # noqa: PLR0913, C901, PLR0912, PLR0915 - one record, one version, one change set
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
) -> WorkItemView:
    """Edit fields (never status or assignment). Unchanged input: no new version, no event."""
    record = await _for_action(session, subject, wtype, "edit", record_id)
    if _closed(record):
        raise Conflict(code="record_closed", params={"status": record.status})
    cat = await config.load(session, wtype)
    cleaned, problems = _check_fields(values, creating=False)
    priority_sent = "priority" in values
    manual, priority_reason, priority_problems = (
        _priority_input(values) if priority_sent else (None, None, [])
    )
    problems += priority_problems
    if priority_sent and not await _may(session, subject, wtype, "change_priority", record.id):
        raise PermissionDenied(
            params={"permission": wtype.permission("change_priority"), "reason": NO_PERMISSION}
        )
    if "channel" in cleaned and record.channel not in {Channel.PHONE, Channel.WALK_UP}:
        problems.append(("channel", "channel_reserved"))
    await _may_change_analysis(
        session, subject, wtype, record, [n for n in ANALYSIS_FIELDS if n in cleaned]
    )
    if problems:
        raise _errors(problems)
    problems += await _check_people(session, cleaned)
    if "site_id" in cleaned and cleaned["site_id"] != record.site_id:
        problems += await _check_units(session, {"site_id": cleaned["site_id"]})
    if "department_id" in cleaned and cleaned["department_id"] != record.department_id:
        problems += await _check_units(session, {"department_id": cleaned["department_id"]})
    if "category_id" in cleaned:
        problems += await _check_category(
            session, wtype, cleaned["category_id"], current=record.category_id
        )
    if "level" in cleaned:
        problems += _check_level(cat, cleaned["level"], current=record.level)
    problems += _check_problem_fields(wtype, cat, cleaned, record)
    custom, custom_problems = await _custom_in(
        session, wtype, values, current=record.custom or {}, creating=False
    )
    problems += custom_problems
    emptied = {
        f"custom.{k}": None for k in (record.custom or {}) if custom is not None and k not in custom
    }
    problems += await templates.emptied_required(
        session,
        record.template_id,
        {
            **{name: getattr(record, name) for name in cleaned},
            **_flat(record.custom or {}),
        },
        {**cleaned, **(_flat(custom) if custom is not None else {}), **emptied},
    )
    if problems:
        raise await _value_errors(session, wtype, problems)
    columns = {name: value for name, value in cleaned.items() if getattr(record, name) != value}
    if custom is not None and custom != (record.custom or {}):
        columns["custom"] = custom
        columns["custom_text"] = await _custom_text(session, wtype, custom, record.id)
    automated = automation.Automated()
    if columns:
        # Business rules on the edit (REQ-RUL-001, 006), before the priority matrix.
        automated = await _rules_on_edit(session, wtype, record, columns)
    impact = columns.get("impact", record.impact)
    urgency = columns.get("urgency", record.urgency)
    recomputed = False
    if priority_sent and manual is not None:
        if manual != record.priority or record.priority_source != PrioritySource.MANUAL:
            columns |= {"priority": manual, "priority_source": PrioritySource.MANUAL}
    elif "priority" in automated.values:
        pass  # a rule set it (REQ-RUL-006: rules before the matrix)
    elif priority_sent or (
        record.priority_source != PrioritySource.MANUAL and ({"impact", "urgency"} & set(columns))
    ):
        computed = compute_priority(impact, urgency, cat.matrix, cat.default_priority)
        if (computed.priority, computed.source) != (record.priority, record.priority_source):
            columns |= {"priority": computed.priority, "priority_source": computed.source}
            recomputed = True
    if not columns:
        if record.version != expected_version:
            raise await _conflict(session, _stale(record, expected_version), record.id)
        return await _view(session, subject, wtype, record)
    before = _snapshot(record)
    audience_before = _audience(record)
    updated = await _update(session, record, expected_version, columns)
    if "custom" in columns:
        await metadata.mark_used(session, wtype.code.value, list(columns["custom"]))
    reach = await _keep_in_reach(
        session,
        subject,
        wtype,
        updated,
        confirmed=bool(values.get("confirm_lose_access")),
        keep_following=values.get("keep_following"),
    )
    handed_over = reach == LOST
    after = _snapshot(updated)
    # A custom value removed is in `before` only: name it with an empty new value.
    after |= {name: None for name in before if name not in after}
    before |= {name: None for name in after if name not in before}
    automatic = {"priority", "priority_source"} if recomputed else set()
    by_rules = set(automated.values) | (
        {"priority_source"} if "priority" in automated.values else set()
    )
    people = [
        Change(n, before[n], v)
        for n, v in after.items()
        if before[n] != v and n not in automatic and n not in by_rules
    ]
    if people:
        await record_changes(
            session,
            record_type=RECORD_TYPE,
            record_id=updated.id,
            version=updated.version,
            kind="updated",
            changes=people,
            source=source,
            reason=priority_reason,
        )
    if recomputed:
        await record_changes(
            session,
            record_type=RECORD_TYPE,
            record_id=updated.id,
            version=updated.version,
            kind="updated",
            changes=[
                Change(n, before[n], after[n]) for n in sorted(automatic) if before[n] != after[n]
            ],
            source=source,
            automation_ref={"kind": "matrix"},
        )
    await _record_automation(session, updated, automated)
    await record_event(
        session,
        WorkItemUpdated(
            work_item_id=updated.id,
            type=updated.type,
            display_id=updated.display_id,
            status=updated.status,
            status_category=updated.status_category,
            changed_fields=[n for n in after if before[n] != after[n]],
            audience_before=audience_before,
        ),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )
    await _follow_after_handover(session, subject, updated, reach, source)
    if handed_over:
        return WorkItemView(
            record=updated, actions=[], operations=[], history_count=0, visible=False
        )
    return await _view(session, subject, wtype, updated)


# --- status actions -------------------------------------------------------------------------------


async def transition(  # noqa: PLR0913 - the action and its context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    action: WorkItemAction,
    *,
    expected_version: int,
    reason_code: str | None,
    reason_text: str | None,
    source: Source,
    holders: PermissionHolders,
    group_id: uuid.UUID | None = None,
    closing_input: closing.MoveInput | None = None,
) -> WorkItemView:
    """Run a life-cycle action (REQ-INC-046/047). System actions cannot be called.

    Resolve asks for the resolution, close for the closure code; both follow the closure
    rules and the open-work checks (WP-020f), on every path that runs a move.

    Start work on an unassigned record first assigns it to the user (as Take does, with the
    same group rules), then starts it, in one transaction; both steps are in history (QA BUG-05).
    """
    if action not in ACTION_PERMISSION:
        raise Conflict(code="invalid_transition", params={"action": action})
    record = await _for_action(session, subject, wtype, ACTION_PERMISSION[action], record_id)
    refused = await _Transitions(session, subject, record).refusal(action.value)
    if refused is not None:
        raise PermissionDenied(code="transition_not_allowed", params={"reason": refused})
    cat = await config.load(session, wtype)
    try:
        step = cat.lifecycle_of(record.lifecycle).transition(record.status, action)
    except InvalidTransition as error:
        raise Conflict(
            code="invalid_transition", params={"from": record.status, "action": action}
        ) from error
    text = (reason_text or "").strip() or None
    problems = reason_problems(
        step, code=reason_code, text=text, allowed_codes=cat.reason_codes(step.reason_list)
    )
    if problems:
        raise _errors(problems, reason_text={"max_length": 500})
    if record.version != expected_version:
        raise await _conflict(session, _stale(record, expected_version), record.id)
    if action == WorkItemAction.START_WORK and record.technician_id is None:
        if await _reason_for(session, subject, wtype, "take", record.id) is not None:
            raise PermissionDenied(
                params={"permission": wtype.permission("take"), "reason": CANNOT_TAKE}
            )
        taken = await _assign(
            session,
            subject,
            wtype,
            record,
            expected_version=expected_version,
            group_id=_take_group(subject, record, group_id),
            technician_id=subject.user_id,
            reason_code=None,
            reason_text=None,
            confirm_lose_access=False,
            source=source,
            holders=holders,
        )
        record = taken.record
        expected_version = record.version
    try:
        step = cat.lifecycle_of(record.lifecycle).transition(record.status, action)
        target = cat.lifecycle_of(record.lifecycle).target(
            record.status,
            action,
            before_cancel=record.status_before_cancel,
            before_pause=record.status_before_pause,
        )
    except InvalidTransition as error:  # pragma: no cover - start work is allowed from assigned
        raise Conflict(
            code="invalid_transition", params={"from": record.status, "action": action}
        ) from error
    closing_step = await closing.before_move(
        session, cat, record, action, closing_input or closing.MoveInput()
    )
    before = _snapshot(record, STAMP_FIELDS)
    changes = await _status_change(
        session, wtype, record, action, target=target, reason_code=reason_code, reason_text=text
    )
    changes.update(closing_step.changes)
    # Rules see a status move as an edit ("status changed to Resolved", REQ-RUL-001); they
    # cannot set the status themselves, so the life cycle stays in charge.
    automated = await _rules_on_edit(session, wtype, record, changes)
    updated = await _update(session, record, expected_version, changes)
    await _record_status(
        session,
        before,
        updated,
        action,
        source=source,
        reason=text,
        automatic=False,
        extra=closing_step.history,
    )
    await _record_automation(session, updated, automated)
    return await _view(session, subject, wtype, updated)


# --- stage moves (ADR-041) -----------------------------------------------------------------------

# The `action` of a status event for a listed move of a staged type (no named action ran).
STAGE_MOVE = "stage_move"


async def move_status(  # noqa: PLR0913 - the move and its context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    target: str,
    expected_version: int,
    reason_code: str | None,
    reason_text: str | None,
    source: Source,
    closing_input: closing.MoveInput | None = None,
) -> WorkItemView:
    """A person's listed status move on a staged type (ADR-041 §8); never a system status.

    Checks in order: the move is listed for the record's path and version, the target is not
    system-only, the edit permission and the move's own (cancel, reopen), the reason, the type's
    guard, then the version.
    """
    if wtype.stages is None:
        raise Conflict(code="stage_move_not_allowed", params={"to": target})
    record = await _for_action(session, subject, wtype, "edit", record_id)
    moved = await _stage_move(
        session,
        wtype,
        record,
        target=target,
        expected_version=expected_version,
        reason_code=reason_code,
        reason_text=reason_text,
        source=source,
        subject=subject,
        given=closing_input or closing.MoveInput(),
    )
    return await _view(session, subject, wtype, moved)


@dataclass(frozen=True)
class StageOffer:
    """A move offered from the current status: whether you may, and why not."""

    transition: StatusTransitionDef
    to_stage: str
    allowed: bool
    reason: str | None


@dataclass(frozen=True)
class StagePanel:
    """A staged record's rail and the moves offered from where it is (ADR-041 §7)."""

    record: WorkItem
    rail: list[RailStage]
    moves: list[StageOffer]


async def stage_panel(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> StagePanel:
    """The rail and the listed moves a person may be offered (system statuses never are)."""
    if wtype.stages is None:
        raise _not_found(wtype)
    record = await _visible(session, subject, wtype, record_id)
    model = await stage_service.load_model(session, wtype, record.lifecycle_version)
    may_edit = await _reason_for(session, subject, wtype, "edit", record.id)
    moves: list[StageOffer] = []
    for t in model.moves_from(record.status, str(record.stage_path)):
        target = model.status(t.to_status)
        if target.set_by == SetBy.SYSTEM:
            continue
        refused = may_edit
        if refused is None and t.permission is not None:
            refused = await _reason_for(session, subject, wtype, t.permission, record.id)
        moves.append(StageOffer(t, target.stage, refused is None, refused))
    return StagePanel(record, await stage_service.rail_of(session, wtype, record), moves)


async def system_stage_move(  # noqa: PLR0913 - the move and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    record: WorkItem,
    *,
    target: str,
    source: Source,
    reason_text: str | None = None,
) -> WorkItem:
    """The approvals code's entry point: the only one that may set a system status (§2)."""
    return await _stage_move(
        session,
        wtype,
        record,
        target=target,
        expected_version=record.version,
        reason_code=None,
        reason_text=reason_text,
        source=source,
        subject=None,
    )


async def _stage_move(  # noqa: PLR0913 - the move and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    record: WorkItem,
    *,
    target: str,
    expected_version: int,
    reason_code: str | None,
    reason_text: str | None,
    source: Source,
    subject: Subject | None,
    given: closing.MoveInput = closing.MoveInput(),  # noqa: B008 - a frozen, empty default
) -> WorkItem:
    model = await stage_service.load_model(session, wtype, record.lifecycle_version)
    try:
        move = plan_move(
            model,
            current=record.status,
            target=target,
            path=str(record.stage_path),
            system=subject is None,
        )
    except MoveRefused as error:
        raise Conflict(code=error.code, params={"from": record.status, "to": target}) from error
    if subject is not None and move.transition.permission is not None:
        await _for_action(session, subject, wtype, move.transition.permission, record.id)
    cat = await config.load(session, wtype)
    text = (reason_text or "").strip() or None
    problems = reason_problems(
        move.transition,
        code=reason_code,
        text=text,
        allowed_codes=cat.reason_codes(move.transition.reason_list),
    )
    if problems:
        raise _errors(problems, reason_text={"max_length": 500})
    _check_move_fields(record, move)
    guard = stage_service.guard_of(record.type)
    refusals = [] if guard is None else await guard.check(session, record, move)
    if refusals:
        raise Conflict(
            code="stage_move_refused",
            params={"reason": refusals[0].code, "count": len(refusals)},
        )
    if record.version != expected_version:
        raise await _conflict(session, _stale(record, expected_version), record.id)
    # The closing rules by category (WP-020f): entering resolved runs resolve's, closed close's,
    # leaving a final status clears the resolution as a reopen does.
    closing_step = await closing.before_move(
        session, cat, record, _closing_action(record, move), given
    )
    before = _snapshot(record, (*STAMP_FIELDS, "stage"))
    from_stage = str(record.stage)
    now = _now()
    changes = _staged_changes(record, move, reason_code, text, now) | closing_step.changes
    automated = await _rules_on_edit(session, wtype, record, changes)
    updated = await _update(session, record, expected_version, changes)
    entries = await stage_service.enter(
        session, updated, move.entered, now=now, reason_code=reason_code, reason_text=text
    )
    await _record_stage_move(
        session,
        before,
        updated,
        move=move,
        from_stage=from_stage,
        entries=entries,
        source=source,
        reason=text,
        extra=closing_step.history,
    )
    await _record_automation(session, updated, automated)
    return updated


def _closing_action(record: WorkItem, move: Move) -> WorkItemAction:
    """Which closing rules a stage move runs, from the categories it moves between."""
    old = StatusCategory(record.status_category)
    new = move.landed.category
    if old in FINAL_CATEGORIES and new not in FINAL_CATEGORIES:
        return WorkItemAction.REOPEN
    if new == StatusCategory.CLOSED and old != StatusCategory.CLOSED:
        return WorkItemAction.CLOSE
    if new == StatusCategory.RESOLVED and old != StatusCategory.RESOLVED:
        return WorkItemAction.RESOLVE
    return WorkItemAction.START_WORK  # no closing rules


def _check_move_fields(record: WorkItem, move: Move) -> None:
    """The fields the move's transition asks for must have a value (ADR-041 §4, REQ-CHG-026)."""
    asked = move.transition.required_fields
    if not asked:
        return
    values = {name: getattr(record, name, None) for name in asked if not name.startswith("custom.")}
    missing = missing_fields(asked, values, record.custom or {})
    if missing:
        raise _errors([(name, "required") for name in missing])


def _staged_changes(
    record: WorkItem,
    move: Move,
    reason_code: str | None,
    reason_text: str | None,
    now: datetime,
) -> dict[str, Any]:
    """Columns of a stage-engine move: where it landed, the clock and the time stamps."""
    old = StatusCategory(record.status_category)
    new = move.landed.category
    clock = move_pause_clock(
        PauseClock(record.paused_since, record.paused_seconds), old=old, new=new, now=now
    )
    changes: dict[str, Any] = {
        "status": move.landed.code,
        "status_category": new,
        "stage": move.landed.stage,
        "status_changed_at": now,
        "status_reason_code": reason_code,
        "status_reason_text": reason_text,
        "paused_since": clock.paused_since,
        "paused_seconds": clock.paused_seconds,
    }
    if new == StatusCategory.RESOLVED and record.resolved_at is None:
        changes["resolved_at"] = now
    if new == StatusCategory.CLOSED:
        changes["closed_at"] = now
        changes["resolved_at"] = record.resolved_at or now
    if old in FINAL_CATEGORIES and new not in FINAL_CATEGORIES:  # a reopen (a listed move)
        changes |= {
            "reopen_count": record.reopen_count + 1,
            "last_reopened_at": now,
            "resolved_at": None,
            "closed_at": None,
        }
    return changes


async def _record_stage_move(  # noqa: PLR0913 - the move, what it did and its source, explicit
    session: AsyncSession,
    before: Mapping[str, Any],
    record: WorkItem,
    *,
    move: Move,
    from_stage: str,
    entries: Sequence[Any],
    source: Source,
    reason: str | None,
    extra: Sequence[Change] = (),
) -> None:
    after = _snapshot(record, (*STAMP_FIELDS, "stage"))
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="status",
        changes=[Change(n, before[n], v) for n, v in after.items() if before[n] != v] + list(extra),
        source=source,
        reason=reason,
    )
    await record_event(
        session,
        WorkItemStatusChanged(
            work_item_id=record.id,
            type=record.type,
            display_id=record.display_id,
            status=record.status,
            status_category=record.status_category,
            action=STAGE_MOVE,
            from_status=str(before["status"]),
            to_status=record.status,
            automatic=move.target.set_by == SetBy.SYSTEM,
        ),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )
    if entries:
        await record_event(
            session,
            WorkItemStageChanged(
                work_item_id=record.id,
                type=record.type,
                display_id=record.display_id,
                status=record.status,
                status_category=record.status_category,
                from_stage=from_stage,
                to_stage=str(record.stage),
                stages_entered=list(move.entered),
                entry_id=entries[-1].id,
                path=str(record.stage_path),
                automatic=move.target.set_by == SetBy.SYSTEM,
            ),
            aggregate_id=record.id,
            aggregate_version=record.version,
        )


# --- a release's own fields (WP-058a; REQ-REL-002..005) -----------------------------------------


@dataclass(frozen=True)
class ReleaseDetailsView:
    """A release and its own fields (None before any is set)."""

    record: WorkItem
    details: WorkItemReleaseDetails | None


def _detail_values(row: WorkItemReleaseDetails | None) -> dict[str, Any]:
    return {n: (getattr(row, n) if row is not None else None) for n in release_rules.DETAIL_FIELDS}


def _release_only(wtype: WorkItemType) -> None:
    if wtype.code is not WorkItemTypeCode.RELEASE:
        raise _not_found(wtype)


async def release_details(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> ReleaseDetailsView:
    """A release's own fields, within your view scope (404 otherwise)."""
    _release_only(wtype)
    record = await _visible(session, subject, wtype, record_id)
    row = await session.get(WorkItemReleaseDetails, (config.tenant_of(session), record.id))
    return ReleaseDetailsView(record, row)


def _clean_detail(name: str, value: Any) -> Any:  # noqa: ANN401 - field values of several types
    """Trimmed text (blank: none), sanitised notes; other values as given."""
    if isinstance(value, str):
        if name == "release_notes":
            cleaned = sanitize_html(value)
            return None if is_blank(cleaned) else cleaned
        return " ".join(value.split()) or None
    return value


async def _detail_problems(
    session: AsyncSession,
    wtype: WorkItemType,
    current: Mapping[str, Any],
    given: Mapping[str, Any],
    risk_reason: str | None,
) -> list[tuple[str, str]]:
    problems = release_rules.detail_problems({**current, **given})
    cat = await config.load(session, wtype)
    for name, pick in (
        ("release_type", PickList.RELEASE_TYPE),
        ("release_reason", PickList.RELEASE_REASON),
    ):
        # A retired value is never newly chosen; a release that has it keeps it (REQ-REL-003).
        value = given.get(name)
        if value is not None and value != current[name] and value not in cat.reason_codes(pick):
            problems.append((name, "invalid_choice"))
    people = {
        n: given[n]
        for n in ("release_manager_id", "release_engineer_id")
        if given.get(n) is not None
    }
    if people:
        found = await user_names(session, [str(v) for v in people.values()])
        problems += [(n, "user_not_found") for n, v in people.items() if str(v) not in found]
    # REQ-REL-004 AC3: a risk set by hand says why, in history.
    if "risk" in given and given["risk"] != current["risk"] and not risk_reason:
        problems.append(("risk_reason", "reason_required"))
    return problems


async def update_release_details(  # noqa: PLR0913 - the change and its context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
    risk_reason: str | None = None,
) -> ReleaseDetailsView:
    """Change the fields you send (If-Match on the release). Unchanged input: no new version."""
    _release_only(wtype)
    record = await _for_action(session, subject, wtype, "edit", record_id)
    if _closed(record):
        raise Conflict(code="record_closed", params={"status": record.status})
    if record.version != expected_version:
        raise await _conflict(session, _stale(record, expected_version), record.id)
    tenant = config.tenant_of(session)
    row = await session.get(WorkItemReleaseDetails, (tenant, record.id))
    current = _detail_values(row)
    given = {n: _clean_detail(n, v) for n, v in values.items() if n in release_rules.DETAIL_FIELDS}
    reason = (risk_reason or "").strip() or None
    problems = await _detail_problems(session, wtype, current, given, reason)
    if problems:
        raise _errors(problems)
    changed = {n: v for n, v in given.items() if v != current[n]}
    if not changed:
        return ReleaseDetailsView(record, row)
    if row is None:
        row = WorkItemReleaseDetails(tenant_id=tenant, work_item_id=record.id)
        session.add(row)
    for name, value in changed.items():
        setattr(row, name, value)
    await session.flush()
    audience = _audience(record)
    updated = await _update(
        session,
        record,
        expected_version,
        {"custom_text": await _custom_text(session, wtype, record.custom or {}, record.id)},
    )
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=updated.id,
        version=updated.version,
        kind="updated",
        changes=[Change(n, _json(current[n]), _json(v)) for n, v in changed.items()],
        source=source,
        reason=reason,
    )
    await record_event(
        session,
        WorkItemUpdated(
            work_item_id=updated.id,
            type=updated.type,
            display_id=updated.display_id,
            status=updated.status,
            status_category=updated.status_category,
            changed_fields=sorted(changed),
            audience_before=audience,
        ),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )
    return ReleaseDetailsView(updated, row)


# --- the requester replies (WP-020f) --------------------------------------------------------------

REQUESTER_REPLY = "requester_reply"


async def system_move(  # noqa: PLR0913 - the move and its context, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    cat: Catalogue,
    record: WorkItem,
    action: WorkItemAction,
    *,
    source: Source,
    rule: str = REQUESTER_REPLY,
    given: closing.MoveInput | None = None,
    by_requester: bool = True,
) -> WorkItem:
    """A move made for the requester's act (a reply, a confirmation) or by the system.

    The requester's own acts (reply, confirm, reject) are theirs, never automation (WP-020f
    BUG-03): history keeps them as the person, from their channel, with `requester_action`
    saying what they did. Only the system's own moves (auto-close) are automatic.
    """
    target = cat.lifecycle_of(record.lifecycle).target(
        record.status,
        action,
        before_cancel=record.status_before_cancel,
        before_pause=record.status_before_pause,
    )
    step = await closing.before_move(session, cat, record, action, given or closing.MoveInput())
    before = _snapshot(record, STAMP_FIELDS)
    changes = await _status_change(
        session, wtype, record, action, target=target, reason_code=None, reason_text=None
    )
    changes.update(step.changes)
    updated = await _update(session, record, record.version, changes)
    await _record_status(
        session,
        before,
        updated,
        action,
        source=source,
        reason=None,
        automatic=not by_requester,
        rule=rule,
        extra=[Change("requester_action", None, requester_action(rule, action))]
        if by_requester
        else (),
    )
    return updated


async def set_fields(  # noqa: PLR0913 - the record, its version, the change and its reason
    session: AsyncSession,
    record: WorkItem,
    columns: Mapping[str, Any],
    *,
    expected_version: int,
    source: Source,
    reason: str | None = None,
) -> WorkItem:
    """Columns a service sets after its own checks (a known error marked; WP-044b).

    If-Match, field history with the reason, and the usual update event.
    """
    audience_before = _audience(record)
    before = {name: getattr(record, name) for name in columns}
    updated = await _update(session, record, expected_version, columns)
    changes = [Change(n, _json(before[n]), _json(v)) for n, v in columns.items() if before[n] != v]
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=updated.id,
        version=updated.version,
        kind="updated",
        changes=changes,
        source=source,
        reason=reason,
    )
    await record_event(
        session,
        WorkItemUpdated(
            work_item_id=updated.id,
            type=updated.type,
            display_id=updated.display_id,
            status=updated.status,
            status_category=updated.status_category,
            changed_fields=sorted(columns),
            audience_before=audience_before,
        ),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )
    return updated


async def set_status(  # noqa: PLR0913 - the move, its version and its record, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    record: WorkItem,
    action: WorkItemAction,
    *,
    target: str,
    expected_version: int,
    source: Source,
    extra: Sequence[Change] = (),
) -> WorkItem:
    """A system status a person's act sets (a problem merged, or its undo; WP-044b).

    Not a transition: the caller checked who may do it. History keeps it as the person, with
    `extra` saying what else happened; the usual status event follows.
    """
    before = _snapshot(record, STAMP_FIELDS)
    changes = await _status_change(
        session, wtype, record, action, target=target, reason_code=None, reason_text=None
    )
    updated = await _update(session, record, expected_version, changes)
    await _record_status(
        session, before, updated, action, source=source, reason=None, automatic=False, extra=extra
    )
    return updated


async def decided_move(  # noqa: PLR0913 - the move and what the approval decided, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    cat: Catalogue,
    record: WorkItem,
    action: WorkItemAction,
    *,
    approval_status: str,
    technician_id: uuid.UUID | None,
    source: Source,
    reason_code: str | None = None,
) -> WorkItem:
    """The approval engine's move (WP-030 s2): approve, reject, or a withdrawal's cancel.

    The decider's own act, never automation: history keeps them as the person, from their
    channel, with the record's new approval status. On approval the item's technician (after
    approval, REQ-SR-008 AC2) is set in the same save, then the usual move to "assigned".
    """
    target = cat.lifecycle_of(record.lifecycle).target(
        record.status,
        action,
        before_cancel=record.status_before_cancel,
        before_pause=record.status_before_pause,
    )
    old_approval, old_technician = record.approval_status, record.technician_id
    audience = _audience(record)
    assigning = technician_id != old_technician
    before = _snapshot(record, STAMP_FIELDS)
    changes = await _status_change(
        session, wtype, record, action, target=target, reason_code=reason_code, reason_text=None
    )
    changes["approval_status"] = approval_status
    if assigning:
        changes["technician_id"] = technician_id
    updated = await _update(session, record, record.version, changes)
    extra = [Change("approval_status", old_approval, approval_status)]
    if assigning:
        extra.append(
            Change(
                "technician_id",
                None if old_technician is None else str(old_technician),
                None if technician_id is None else str(technician_id),
            )
        )
    await _record_status(
        session, before, updated, action, source=source, reason=None, automatic=False, extra=extra
    )
    if not assigning:
        return updated
    await record_event(
        session,
        WorkItemAssigned(
            work_item_id=updated.id,
            type=updated.type,
            display_id=updated.display_id,
            status=updated.status,
            status_category=updated.status_category,
            group_id=updated.group_id,
            technician_id=updated.technician_id,
            audience_before=audience,
        ),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )
    move = (
        after_assignment(
            cat.lifecycle_of(updated.lifecycle),
            updated.status,
            had_technician=False,
            has_technician=True,
        )
        if cat.auto_status_on_assign
        else None
    )
    if move is None:
        return updated
    before = _snapshot(updated, STAMP_FIELDS)
    moved = await _status_change(
        session,
        wtype,
        updated,
        move,
        target=cat.lifecycle_of(updated.lifecycle).target(updated.status, move, before_cancel=None),
        reason_code=None,
        reason_text=None,
    )
    updated = await _update(session, updated, updated.version, moved)
    await _record_status(session, before, updated, move, source=source, reason=None, automatic=True)
    return updated


def requester_action(rule: str, action: WorkItemAction) -> str:
    """What the requester did, as history words it: a reply that reopened or resumed."""
    if rule == REQUESTER_REPLY:
        return f"{rule}_reopened" if action == WorkItemAction.REOPEN else f"{rule}_resumed"
    return rule


async def on_requester_reply(  # noqa: PLR0913 - the reply and its context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record: WorkItem,
    *,
    body: str,
    source: Source,
    holders: PermissionHolders,
) -> WorkItem | None:
    """What a requester's public reply does to the record (REQ-INC-051, REQ-INC-098).

    Waiting on them: back to in progress where the status says so. Resolved or closed: within
    the reopen window it reopens; after it a new record follows this one, which is returned so
    the requester can be told its ID.
    """
    cat = await config.load(session, wtype)
    category = StatusCategory(record.status_category)
    allowed = set(cat.lifecycle_of(record.lifecycle).actions_from(record.status))
    if category == StatusCategory.PAUSED:
        status = next((s for s in cat.statuses if s.code == record.status), None)
        resumes = status is not None and status.resume_on_requester_reply
        if resumes and WorkItemAction.RESUME in allowed:
            await system_move(session, wtype, cat, record, WorkItemAction.RESUME, source=source)
        return None
    if category not in {StatusCategory.RESOLVED, StatusCategory.CLOSED}:
        return None
    done_at = record.closed_at if category == StatusCategory.CLOSED else record.resolved_at
    if within_reopen_window(done_at, datetime.now(UTC), cat.closure.reopen_window_days):
        if WorkItemAction.REOPEN in allowed:
            await system_move(session, wtype, cat, record, WorkItemAction.REOPEN, source=source)
        return None
    return await _follow_up(
        session, subject, wtype, record, body=body, source=source, holders=holders
    )


async def _follow_up(  # noqa: PLR0913 - the reply and its context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record: WorkItem,
    *,
    body: str,
    source: Source,
    holders: PermissionHolders,
) -> WorkItem | None:
    """A new record from a late reply, following the old one (REQ-INC-098 AC2).

    It keeps the old record's requester, subject, site, department and category; the reply is
    its description. When the new record cannot be created (a template that requires more),
    the reply stays on the closed record and its history says so.
    """
    values = {
        "subject": record.subject,
        "description": body,
        "requester_id": record.requester_id,
        "on_behalf_of_id": record.on_behalf_of_id,
        "site_id": record.site_id,
        "department_id": record.department_id,
        "category_id": record.category_id,
    }
    try:
        async with session.begin_nested():
            created = await create(session, subject, wtype, values, source=source, holders=holders)
            follow = await _update(
                session, created.record, created.record.version, {"follows_id": record.id}
            )
            # WP-020e: the follow-up is also a `follows` link, shown on both records. Imported
            # here because the parts service builds on this one.
            from app.modules.work_items.service import parts  # noqa: PLC0415

            await parts.add_follows(session, follow, record, source=source)
    except (ValidationFailed, PermissionDenied, Conflict):
        await record_changes(
            session,
            record_type=RECORD_TYPE,
            record_id=record.id,
            version=record.version,
            kind="child_changed",
            changes=[Change("follow_up_not_created", None, new=True)],
            source=source,
        )
        return None
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="child_added",
        changes=[Change("followed_by", None, follow.display_id)],
        source=source,
    )
    return follow


# --- assignment -----------------------------------------------------------------------------------


async def _assign(  # noqa: PLR0913, C901, PLR0912, PLR0915 - one assignment, every rule in order
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record: WorkItem,
    *,
    expected_version: int,
    group_id: uuid.UUID | None,
    technician_id: uuid.UUID | None,
    reason_code: str | None,
    reason_text: str | None,
    confirm_lose_access: bool,
    keep_following: bool | None = None,
    source: Source,
    holders: PermissionHolders,
) -> WorkItemView:
    if _closed(record):
        raise Conflict(code="record_closed", params={"status": record.status})
    cat = await config.load(session, wtype)
    text = (reason_text or "").strip() or None
    problems = await _check_assignment(
        session, subject, wtype, holders, group_id=group_id, technician_id=technician_id
    )
    moving_groups = record.group_id is not None and group_id != record.group_id
    if moving_groups:
        codes = cat.reason_codes(ReasonList.REASSIGN)
        if reason_code is None:
            problems.append(("reason_code", "required"))
        elif reason_code not in codes:
            problems.append(("reason_code", "invalid_choice"))
        elif reason_code == "other" and text is None:
            problems.append(("reason_text", "required"))
    elif reason_code is not None and reason_code not in cat.reason_codes(ReasonList.REASSIGN):
        problems.append(("reason_code", "invalid_choice"))
    if text is not None and len(text) > PRIORITY_REASON_MAX:
        problems.append(("reason_text", "value_too_long"))
    problems += await templates.emptied_required(
        session,
        record.template_id,
        {"group_id": record.group_id, "technician_id": record.technician_id},
        {"group_id": group_id, "technician_id": technician_id},
    )
    if problems:
        raise _errors(problems)
    if (group_id, technician_id) == (record.group_id, record.technician_id):
        if record.version != expected_version:
            raise await _conflict(session, _stale(record, expected_version), record.id)
        return await _view(session, subject, wtype, record)
    had_technician = record.technician_id is not None
    was_assigned = record.group_id is not None or had_technician
    columns: dict[str, Any] = {"group_id": group_id, "technician_id": technician_id}
    # Rules see the assignment as an edit; a move to a new group with nobody named may then
    # be auto-assigned inside that group (REQ-RUL-001, REQ-ASG-001).
    moved_to = group_id if group_id is not None and group_id != record.group_id else None
    automated = await _rules_on_edit(
        session,
        wtype,
        record,
        columns,
        eligible=(lambda: _eligible(session, subject, wtype, holders))
        if moved_to is not None and technician_id is None
        else None,
    )
    technician_id = columns["technician_id"]
    if technician_id is not None and record.first_assigned_at is None:
        columns["first_assigned_at"] = _now()
    if was_assigned:
        columns["reassignment_count"] = record.reassignment_count + 1
    before = _snapshot(record, ("group_id", "technician_id", "reassignment_count"))
    audience_before = _audience(record)
    updated = await _update(session, record, expected_version, columns)
    reach = await _keep_in_reach(
        session,
        subject,
        wtype,
        updated,
        confirmed=confirm_lose_access,
        keep_following=keep_following,
    )
    handed_over = reach == LOST
    after = _snapshot(updated, ("group_id", "technician_id", "reassignment_count"))
    # What the rules or auto-assignment set has its own entries, with the rule named.
    chosen = {n: v for n, v in after.items() if n not in automated.values}
    changes = [Change(n, before[n], v) for n, v in chosen.items() if before[n] != v]
    if reason_code is not None:
        changes.append(Change("assignment_reason", None, reason_code))
    if handed_over:
        changes.append(Change("handed_over_out_of_reach", None, new=True))
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=updated.id,
        version=updated.version,
        kind="updated",
        changes=changes,
        source=source,
        reason=text,
    )
    await _record_automation(session, updated, automated)
    await record_event(
        session,
        WorkItemAssigned(
            work_item_id=updated.id,
            type=updated.type,
            display_id=updated.display_id,
            status=updated.status,
            status_category=updated.status_category,
            group_id=updated.group_id,
            technician_id=updated.technician_id,
            audience_before=audience_before,
        ),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )
    if cat.auto_status_on_assign:
        move = after_assignment(
            cat.lifecycle_of(updated.lifecycle),
            updated.status,
            had_technician=had_technician,
            has_technician=technician_id is not None,
        )
        if move is not None:
            stamps = _snapshot(updated, STAMP_FIELDS)
            target = cat.lifecycle_of(updated.lifecycle).target(
                updated.status, move, before_cancel=None
            )
            status_columns = await _status_change(
                session, wtype, updated, move, target=target, reason_code=None, reason_text=None
            )
            updated = await _update(session, updated, updated.version, status_columns)
            await _record_status(
                session, stamps, updated, move, source=source, reason=None, automatic=True
            )
    await _follow_after_handover(session, subject, updated, reach, source)
    if handed_over:
        return WorkItemView(
            record=updated, actions=[], operations=[], history_count=0, visible=False
        )
    return await _view(session, subject, wtype, updated)


async def assign(  # noqa: PLR0913 - the assignment and its context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    expected_version: int,
    group_id: uuid.UUID | None,
    technician_id: uuid.UUID | None,
    reason_code: str | None,
    reason_text: str | None,
    confirm_lose_access: bool,
    keep_following: bool | None = None,
    source: Source,
    holders: PermissionHolders,
) -> WorkItemView:
    """Set group and technician (REQ-INC-053/055); a hand-over needs confirmation (D-053, D-068)."""
    record = await _for_action(session, subject, wtype, "assign", record_id)
    return await _assign(
        session,
        subject,
        wtype,
        record,
        expected_version=expected_version,
        group_id=group_id,
        technician_id=technician_id,
        reason_code=reason_code,
        reason_text=reason_text,
        confirm_lose_access=confirm_lose_access,
        keep_following=keep_following,
        source=source,
        holders=holders,
    )


def _take_group(subject: Subject, record: WorkItem, group_id: uuid.UUID | None) -> uuid.UUID | None:
    """The group a take lands in: the record's, else the chosen one, else the user's only one."""
    if record.group_id is not None:
        return record.group_id
    mine = subject.group_ids
    if group_id is not None:
        if group_id not in mine:
            raise _errors([("group_id", "group_not_yours")])
        return group_id
    if len(mine) == 1:
        return next(iter(mine))
    if len(mine) > 1:
        raise _errors([("group_id", "group_required")])
    return None


async def take(  # noqa: PLR0913 - the record and its context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    expected_version: int,
    group_id: uuid.UUID | None,
    source: Source,
    holders: PermissionHolders,
) -> WorkItemView:
    """Become the technician (REQ-INC-054); sets the group when only one of yours can apply."""
    record = await _for_action(session, subject, wtype, "take", record_id)
    if record.version != expected_version:
        raise await _conflict(session, _stale(record, expected_version), record.id)
    if record.technician_id == subject.user_id:
        raise Conflict(code="already_yours")
    if record.technician_id is not None:
        names = await user_names(session, [str(record.technician_id)])
        raise Conflict(
            code="already_taken", params={"taken_by": names.get(str(record.technician_id), "")}
        )
    return await _assign(
        session,
        subject,
        wtype,
        record,
        expected_version=expected_version,
        group_id=_take_group(subject, record, group_id),
        technician_id=subject.user_id,
        reason_code=None,
        reason_text=None,
        confirm_lose_access=False,
        source=source,
        holders=holders,
    )


# --- due dates set by hand (REQ-SLA-028, REQ-INC-012, D-115 D11) -------------------------------


async def set_due_date(  # noqa: PLR0913 - the record, the change and its context, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    kind: str,
    due_at: datetime | None,
    reason: str,
    expected_version: int,
    source: Source,
) -> WorkItemView:
    """Set a target's due date by hand, or clear it (`due_at` None); always with a reason.

    The date then stays through priority and policy changes until cleared; clearing
    recalculates it from the record's SLA (REQ-SLA-028 AC1, AC2).
    """
    record = await _for_action(session, subject, wtype, "edit_due_dates", record_id)
    if record.version != expected_version:
        raise await _conflict(session, _stale(record, expected_version), record.id)
    if not sla_glue.has_sla(record) or kind not in sla_glue.DUE_COLUMNS:
        raise NotFound(code="sla_target_not_found", params={"kind": kind})
    now = _now()
    problems: list[tuple[str, str]] = []
    if not reason.strip():
        problems.append(("reason", "required"))
    if due_at is not None and due_at <= now:
        problems.append(("due_at", "due_in_past"))
    if problems:
        raise _errors(problems)
    audience_before = _audience(record)
    columns = await sla_glue.set_due(
        session, record, kind, due_at, reason=reason.strip(), now=now, actor=subject.user_id
    )
    change = sla_glue.due_change(record, kind, columns)
    changed = {k: v for k, v in columns.items() if getattr(record, k) != v}
    try:
        updated = await WorkItemRepository(session).update(
            record.id, expected_version=expected_version, changes=changed
        )
    except Conflict as error:
        raise await _conflict(session, error, record.id) from error
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=updated.id,
        version=updated.version,
        kind="updated",
        changes=[change],
        source=source,
        reason=reason.strip(),
    )
    await record_event(
        session,
        WorkItemUpdated(
            work_item_id=updated.id,
            type=updated.type,
            display_id=updated.display_id,
            status=updated.status,
            status_category=updated.status_category,
            changed_fields=sorted({change.field, *changed}),
            audience_before=audience_before,
        ),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )
    return await _view(session, subject, wtype, updated)


async def sla_fired(
    session: AsyncSession,
    record_id: uuid.UUID,
    columns: Mapping[str, Any],
    fired: Sequence[Any],
    *,
    now: datetime,
) -> None:
    """The SLA waker fired on this record: stamp it, with history from source "sla".

    A warning or breach changes the record's SLA state columns; each escalation level that ran
    is a history line of its own (REQ-SLA-022 AC1). The change event turns every open list and
    record live (REQ-SLA-019 AC1). The record row is already locked (sla's `LockHook`).
    """
    del now
    record = await session.scalar(select(WorkItem).where(WorkItem.id == record_id))
    if record is None:
        return
    changed = {k: v for k, v in columns.items() if getattr(record, k) != v}
    lines = sla_glue.fired_changes(record, changed, list(fired))
    if not lines:
        return
    audience_before = _audience(record)
    updated = await WorkItemRepository(session).update(
        record.id, expected_version=record.version, changes=changed
    )
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=updated.id,
        version=updated.version,
        kind="updated",
        changes=lines,
        source="sla",
    )
    await record_event(
        session,
        WorkItemUpdated(
            work_item_id=updated.id,
            type=updated.type,
            display_id=updated.display_id,
            status=updated.status,
            status_category=updated.status_category,
            changed_fields=sorted({line.field for line in lines}),
            audience_before=audience_before,
        ),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )


@dataclass(frozen=True, slots=True)
class SlaPanel:
    """The record's SLA panel (REQ-SLA-038).

    sla's view, the names it shows, and whether the reader may set due dates by hand.
    """

    sla: sla_glue.SlaRecordView
    names: Mapping[str, str]
    may_set_due_dates: bool


async def sla_panel(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> SlaPanel:
    """The SLA of one record the subject may see (else 404)."""
    record = await _visible(session, subject, wtype, record_id)
    view = await sla_glue.record_view(session, record)
    people = sorted({str(t.manual_by) for t in view.targets if t.manual_by})
    refused = await _reason_for(session, subject, wtype, "edit_due_dates", record.id)
    return SlaPanel(
        sla=view,
        names=await user_names(session, people) if people else {},
        may_set_due_dates=refused is None and sla_glue.has_sla(record) and not _closed(record),
    )


# --- trash ----------------------------------------------------------------------------------------


async def remove(  # noqa: PLR0913 - the record, its version and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Move to the trash (REQ-WI-020)."""
    record = await _for_action(session, subject, wtype, "delete", record_id)
    try:
        deleted = await WorkItemRepository(session).soft_delete(
            record.id, expected_version=expected_version
        )
    except Conflict as error:
        raise await _conflict(session, error, record.id) from error
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=deleted.version,
        kind="deleted",
        changes=[],
        source=source,
    )
    await record_event(
        session,
        WorkItemDeleted(
            work_item_id=record.id,
            type=record.type,
            display_id=record.display_id,
            status=record.status,
            status_category=record.status_category,
        ),
        aggregate_id=record.id,
        aggregate_version=deleted.version,
    )


async def restore(  # noqa: PLR0913 - the record, its version and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> WorkItemView:
    """Take out of the trash, exactly as it was."""
    if not subject.holds(wtype.permission("delete")):
        raise _not_found(wtype)
    record = await session.scalar(
        staff_rows(subject, wtype, trash=True, permission="delete").where(WorkItem.id == record_id)
    )
    if record is None:
        raise _not_found(wtype)
    if record.version != expected_version:
        raise await _conflict(session, _stale(record, expected_version), record.id)
    record.deleted_at = None
    record.version += 1
    record.updated_at = _now()
    record.updated_by = subject.user_id
    await session.flush()
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="restored",
        changes=[],
        source=source,
    )
    await record_event(
        session,
        WorkItemRestored(
            work_item_id=record.id,
            type=record.type,
            display_id=record.display_id,
            status=record.status,
            status_category=record.status_category,
        ),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )
    return await _view(session, subject, wtype, record)


# --- for the conversation service (service/conversations.py) -----------------------------------

visible_record = _visible
record_for_action = _for_action
may = _may
audience_of = _audience
now = _now
field_errors = _errors
now = _now


async def update_columns(
    session: AsyncSession, record: WorkItem, expected_version: int, changes: Mapping[str, Any]
) -> WorkItem:
    """Versioned update of a work item's columns (409 explains who changed what)."""
    return await _update(session, record, expected_version, changes)


def stale(current_version: int, expected_version: int) -> Conflict:
    """409 version_conflict for a child record (a conversation entry)."""
    return Conflict(
        code="version_conflict",
        params={"expected_version": expected_version, "current_version": current_version},
    )


# --- automated changes (triggers, a move's "after" actions; WP-029 part 2) ------------------------


async def automated_update(  # noqa: PLR0913 - the record, the values and who makes them, explicit
    session: AsyncSession,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    values: Mapping[str, Any],
    *,
    ref: Mapping[str, Any],
    cause_id: uuid.UUID,
    source: Source = "rule",
) -> list[str]:
    """Set fields as a trigger, through the same save path (REQ-RUL-009, 010).

    Business rules run again and the matrix follows impact and urgency; history names the
    trigger (source `rule`; an SLA escalation level passes `sla`), and the event carries the
    trigger's run as its cause so the loop guard sees the chain. Returns the fields that changed
    (empty: nothing to change).
    """
    record = await session.scalar(_rows(wtype).where(WorkItem.id == record_id).with_for_update())
    if record is None:
        raise _not_found(wtype)
    if _closed(record):
        raise Conflict(code="record_closed", params={"status": record.status})
    columns = await _automated_columns(session, wtype, record, values)
    if not columns:
        return []
    automated = await _rules_on_edit(session, wtype, record, columns)
    if "priority" in columns:
        columns["priority_source"] = PrioritySource.RULE
    elif {"impact", "urgency"} & set(columns) and record.priority_source != PrioritySource.MANUAL:
        cat = await config.load(session, wtype)
        computed = compute_priority(
            columns.get("impact", record.impact),
            columns.get("urgency", record.urgency),
            cat.matrix,
            cat.default_priority,
        )
        columns |= {"priority": computed.priority, "priority_source": computed.source}
    before = _snapshot(record)
    audience_before = _audience(record)
    updated = await _update(session, record, record.version, columns)
    after = _snapshot(updated)
    after |= {name: None for name in before if name not in after}
    before |= {name: None for name in after if name not in before}
    changed = [n for n in after if before[n] != after[n]]
    # What the business rules then set has its own entries naming each rule.
    mine = [Change(n, before[n], after[n]) for n in changed if n not in automated.values]
    if mine:
        await record_changes(
            session,
            record_type=RECORD_TYPE,
            record_id=updated.id,
            version=updated.version,
            kind="updated",
            changes=mine,
            source=source,
            automation_ref=dict(ref),
        )
    await _record_automation(session, updated, automated)
    await record_event(
        session,
        WorkItemUpdated(
            work_item_id=updated.id,
            type=updated.type,
            display_id=updated.display_id,
            status=updated.status,
            status_category=updated.status_category,
            changed_fields=changed,
            audience_before=audience_before,
        ),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
        causation_id=cause_id,
    )
    return changed


async def _automated_columns(
    session: AsyncSession, wtype: WorkItemType, record: WorkItem, values: Mapping[str, Any]
) -> dict[str, Any]:
    """A trigger's values as typed columns, only those that differ from the record."""
    columns: dict[str, Any] = {}
    custom = dict(record.custom or {})
    for name, value in values.items():
        if name.startswith("custom."):
            custom[name.removeprefix("custom.")] = value
        elif name in _REFERENCE_INPUTS or name in {"group_id", "technician_id"}:
            columns[name] = uuid.UUID(str(value)) if value else None
        else:
            columns[name] = value
    columns = {n: v for n, v in columns.items() if getattr(record, n) != v}
    cleaned_custom = {k: v for k, v in custom.items() if v is not None}
    if cleaned_custom != (record.custom or {}):
        columns["custom"] = cleaned_custom
        columns["custom_text"] = await _custom_text(session, wtype, cleaned_custom, record.id)
    return columns


async def automation_record(
    session: AsyncSession, wtype: WorkItemType, record_id: uuid.UUID
) -> WorkItem:
    """The record an automation acts on (not in the trash), or 404."""
    record: WorkItem | None = await session.scalar(_rows(wtype).where(WorkItem.id == record_id))
    if record is None:
        raise _not_found(wtype)
    return record


async def automation_facts(
    session: AsyncSession, wtype: WorkItemType, record_id: uuid.UUID
) -> dict[str, Any] | None:
    """A record's current values as triggers see them (None: gone or in the trash)."""
    record = await session.scalar(_rows(wtype).where(WorkItem.id == record_id))
    if record is None:
        return None
    return {
        **_snapshot(record),
        "status": record.status,
        "status_category": record.status_category,
        **await automation.requester_facts(session, record.requester_id),
    }


async def automation_log(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> list[Any]:
    """What automation did on a record (triggers' outcomes, loop stops), for whoever may see it."""
    await _visible(session, subject, wtype, record_id)
    return list(await record_runs(session, record_id))
