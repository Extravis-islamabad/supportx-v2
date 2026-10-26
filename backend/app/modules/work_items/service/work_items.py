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
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any, Literal, Protocol

from sqlalchemy import ColumnElement, Select, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, NotFound, PermissionDenied, ValidationFailed
from app.modules import metadata
from app.modules.identity_access import (
    Subject,
    authorize_stored,
    display_names,
    scope_filter,
    user_contacts,
    user_names,
)
from app.modules.organization import existing_unit_ids, memberships, users_in_groups
from app.modules.work_items.domain.classification import (
    PRIORITY_REASON_MAX,
    Impact,
    Priority,
    PrioritySource,
    Urgency,
    compute_priority,
)
from app.modules.work_items.domain.conversation import FollowReason
from app.modules.work_items.domain.lifecycle import (
    FINAL_CATEGORIES,
    USER_ACTIONS,
    PauseClock,
    ReasonList,
    ReasonMode,
    StatusCategory,
    WorkItemAction,
    after_assignment,
    move_pause_clock,
    reason_problems,
)
from app.modules.work_items.domain.templates import PickList, clean_impact_details, is_custom
from app.modules.work_items.domain.types import (
    DESCRIPTION_MAX,
    Channel,
    WorkItemType,
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
    WorkItemStatusChanged,
    WorkItemUpdated,
)
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemCategory,
    WorkItemConversation,
    WorkItemFollower,
)
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service import followers, templates
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
    HistoryCursor,
    HistoryEntry,
    Source,
    count_saves,
    explain_conflict,
    history_entries,
    record_changes,
)
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


async def _view(  # noqa: C901 - one state per action and operation, flat
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record: WorkItem
) -> WorkItemView:
    cat = await config.load(session, wtype)
    lifecycle = cat.lifecycle
    final = StatusCategory(record.status_category) in FINAL_CATEGORIES
    allowed_now = set(lifecycle.actions_from(record.status))
    reasons: dict[str, str | None] = {}

    async def reason(permission_action: str) -> str | None:
        if permission_action not in reasons:
            reasons[permission_action] = await _reason_for(
                session, subject, wtype, permission_action, record.id
            )
        return reasons[permission_action]

    actions: list[ActionState] = []
    for action in USER_ACTIONS:
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
        actions.append(
            ActionState(
                action,
                allowed=refused is None,
                reason=refused,
                reason_mode=mode,
                reason_list=reason_list,
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


def view_predicates(
    subject: Subject, *, zone: tzinfo, now: datetime
) -> dict[str, ColumnElement[bool]]:
    """Code → predicate of every built-in view, in the order the UI lists them."""
    groups = subject.group_ids
    today = _start_of_today(zone, now)
    return {
        "open": _open(),
        "my_open": and_(_open(), WorkItem.technician_id == subject.user_id),
        "unassigned": and_(_open(), WorkItem.technician_id.is_(None)),
        "my_groups_open": and_(_open(), WorkItem.group_id.in_(groups))
        if groups
        else WorkItem.id.is_(None),
        "waiting": WorkItem.status_category == StatusCategory.PAUSED,
        "resolved": WorkItem.status_category == StatusCategory.RESOLVED,
        "created_today": and_(
            WorkItem.created_at >= today, WorkItem.created_at < today + timedelta(days=1)
        ),
        "updated_by_me": WorkItem.updated_by == subject.user_id,
        "without_sla": and_(_open(), WorkItem.sla_policy_id.is_(None)),
        "closed": WorkItem.status_category == StatusCategory.CLOSED,
        "canceled": WorkItem.status_category == StatusCategory.CANCELED,
        "all": WorkItem.id.is_not(None),
        **_personal(subject, now=now, today_end=today + timedelta(days=1)),
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
    "waiting",
    "resolved",
    "created_today",
    "updated_by_me",
    "without_sla",
    "closed",
    "canceled",
    "all",
)
COUNT_CAP = 1000


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
    if view is not None:
        predicates = view_predicates(subject, zone=zone, now=_now())
        if view not in predicates:
            raise _errors([("view", "invalid_choice")])
        statement = statement.where(predicates[view])
    if tag:
        statement = statement.where(WorkItem.tags.contains([tag]))
    return await paginate(session, statement, query)


async def view_counts(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, *, zone: tzinfo
) -> list[tuple[str, int, bool]]:
    """(view code, count up to COUNT_CAP, capped) for every built-in view."""
    predicates = view_predicates(subject, zone=zone, now=_now())
    base = staff_rows(subject, wtype)
    found: list[tuple[str, int, bool]] = []
    for code in VIEW_CODES:
        limited = base.where(predicates[code]).with_only_columns(WorkItem.id).limit(COUNT_CAP + 1)
        total = int(await session.scalar(select(func.count()).select_from(limited.subquery())) or 0)
        found.append((code, min(total, COUNT_CAP), total > COUNT_CAP))
    return found


# Fields whose history values are user IDs: the page names them (QA BUG-03).
PERSON_FIELDS = frozenset(
    {"requester_id", "on_behalf_of_id", "technician_id", "follower", "follower_access"}
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
    names = await user_names(session, sorted({e.actor_id for e in entries if e.actor_id}))
    named = {
        value
        for e in entries
        for c in e.changes
        if c.field in PERSON_FIELDS or is_custom(c.field)
        for value in (c.old, c.new)
        if isinstance(value, str) and (c.field in PERSON_FIELDS or _is_uuid(value))
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
    if creating and values.get("requester_id") is None:
        problems.append(("requester_id", "required"))
    for name in ("requester_id", "on_behalf_of_id", "site_id", "category_id"):
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


def _check_level(
    cat: Catalogue, level: str | None, *, current: str | None
) -> list[tuple[str, str]]:
    """A level offered for new input; the record's own (perhaps retired) level may stay."""
    if level is None or level == current or level in cat.reason_codes(PickList.LEVEL):
        return []
    return [("level", "invalid_choice")]


SNAPSHOT_FIELDS = (
    "subject",
    "description",
    "requester_id",
    "on_behalf_of_id",
    "channel",
    "site_id",
    "group_id",
    "technician_id",
    "category_id",
    "impact",
    "impact_details",
    "urgency",
    "priority",
    "priority_source",
    "level",
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
    session: AsyncSession, wtype: WorkItemType, custom: Mapping[str, Any]
) -> str | None:
    """Free text of the custom values, kept on the record for search (WP-026, WP-027)."""
    if not custom:
        return None
    return await metadata.text_for_search(session, wtype.code.value, custom)


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
    try:
        return await WorkItemRepository(session).update(
            record.id, expected_version=expected_version, changes=changes
        )
    except Conflict as error:
        raise await _conflict(session, error, record.id) from error


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
) -> None:
    after = _snapshot(record, STAMP_FIELDS)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="status",
        changes=[Change(n, before[n], v) for n, v in after.items() if before[n] != v],
        source=source,
        reason=reason,
        automation_ref={"kind": "auto_move", "rule": "assignment", "action": action}
        if automatic
        else None,
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


async def create(  # noqa: PLR0913, C901, PLR0915 - the new record's inputs and checks, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    values: Mapping[str, Any],
    *,
    source: Source,
    holders: PermissionHolders,
) -> WorkItemView:
    """A new record in the life cycle's first status (or `assigned` when a technician is set)."""
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
    template = await templates.for_create(session, wtype, values.get("template_id"))
    problems += await templates.required_problems(
        session, wtype, template, {**values, **cleaned, **_flat(custom or {})}
    )
    problems += _check_level(cat, cleaned.get("level"), current=None)
    if problems:
        raise _errors(problems)
    problems += await _check_people(session, cleaned)
    problems += await _check_units(session, {"site_id": cleaned.get("site_id")})
    problems += await _check_category(session, wtype, cleaned.get("category_id"), current=None)
    problems += await _check_assignment(
        session, subject, wtype, holders, group_id=group_id, technician_id=technician_id
    )
    if problems:
        raise _errors(problems)
    if cleaned.get("site_id") is None:
        sites = (await memberships(session, cleaned["requester_id"])).site_ids
        if len(sites) == 1:
            cleaned["site_id"] = next(iter(sites))
    if manual is not None:
        priority, priority_source = manual, PrioritySource.MANUAL
    else:
        computed = compute_priority(
            cleaned.get("impact"), cleaned.get("urgency"), cat.matrix, cat.default_priority
        )
        priority, priority_source = computed.priority, computed.source
    initial = next(s.code for s in cat.statuses if not s.system and not s.disabled)
    now = _now()
    channel = cleaned.get("channel") or (Channel.PHONE if source == "ui" else Channel.API)
    number = await next_display_number(session, wtype.counter_key)
    record = WorkItem(
        type=wtype.code,
        display_number=number,
        display_id=f"{cat.prefix}-{number}",
        subject=cleaned["subject"],
        description=cleaned.get("description"),
        requester_id=cleaned["requester_id"],
        on_behalf_of_id=cleaned.get("on_behalf_of_id"),
        channel=channel,
        site_id=cleaned.get("site_id"),
        group_id=group_id,
        technician_id=technician_id,
        category_id=cleaned.get("category_id"),
        impact=cleaned.get("impact"),
        impact_details=cleaned.get("impact_details"),
        urgency=cleaned.get("urgency"),
        priority=priority,
        priority_source=priority_source,
        level=cleaned.get("level"),
        template_id=template.id,
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
    )
    await WorkItemRepository(session).add(record)
    if custom:
        await metadata.mark_used(session, wtype.code.value, list(custom))
    reach = await _keep_in_reach(
        session,
        subject,
        wtype,
        record,
        confirmed=bool(values.get("confirm_lose_access")),
        keep_following=values.get("keep_following"),
    )
    handed_over = reach == LOST
    after = _snapshot(record)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="created",
        changes=[
            Change(name, None, value) for name, value in after.items() if value not in (None, [])
        ],
        source=source,
        reason=priority_reason,
    )
    await record_event(
        session,
        WorkItemCreated(
            work_item_id=record.id,
            type=record.type,
            display_id=record.display_id,
            status=record.status,
            status_category=record.status_category,
        ),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )
    if technician_id is not None and cat.auto_status_on_assign:
        move = after_assignment(
            cat.lifecycle, record.status, had_technician=False, has_technician=True
        )
        if move is not None:
            before = _snapshot(record, STAMP_FIELDS)
            target = cat.lifecycle.target(record.status, move, before_cancel=None)
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
    if problems:
        raise _errors(problems)
    problems += await _check_people(session, cleaned)
    if "site_id" in cleaned and cleaned["site_id"] != record.site_id:
        problems += await _check_units(session, {"site_id": cleaned["site_id"]})
    if "category_id" in cleaned:
        problems += await _check_category(
            session, wtype, cleaned["category_id"], current=record.category_id
        )
    if "level" in cleaned:
        problems += _check_level(cat, cleaned["level"], current=record.level)
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
        raise _errors(problems)
    columns = {name: value for name, value in cleaned.items() if getattr(record, name) != value}
    if custom is not None and custom != (record.custom or {}):
        columns["custom"] = custom
        columns["custom_text"] = await _custom_text(session, wtype, custom)
    impact = columns.get("impact", record.impact)
    urgency = columns.get("urgency", record.urgency)
    recomputed = False
    if priority_sent and manual is not None:
        if manual != record.priority or record.priority_source != PrioritySource.MANUAL:
            columns |= {"priority": manual, "priority_source": PrioritySource.MANUAL}
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
    people = [
        Change(n, before[n], v) for n, v in after.items() if before[n] != v and n not in automatic
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
) -> WorkItemView:
    """Run a life-cycle action (REQ-INC-046/047). System actions cannot be called.

    Start work on an unassigned record first assigns it to the user (as Take does, with the
    same group rules), then starts it, in one transaction; both steps are in history (QA BUG-05).
    """
    if action not in ACTION_PERMISSION:
        raise Conflict(code="invalid_transition", params={"action": action})
    record = await _for_action(session, subject, wtype, ACTION_PERMISSION[action], record_id)
    cat = await config.load(session, wtype)
    try:
        step = cat.lifecycle.transition(record.status, action)
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
        step = cat.lifecycle.transition(record.status, action)
        target = cat.lifecycle.target(
            record.status, action, before_cancel=record.status_before_cancel
        )
    except InvalidTransition as error:  # pragma: no cover - start work is allowed from assigned
        raise Conflict(
            code="invalid_transition", params={"from": record.status, "action": action}
        ) from error
    before = _snapshot(record, STAMP_FIELDS)
    changes = await _status_change(
        session, wtype, record, action, target=target, reason_code=reason_code, reason_text=text
    )
    updated = await _update(session, record, expected_version, changes)
    await _record_status(
        session, before, updated, action, source=source, reason=text, automatic=False
    )
    return await _view(session, subject, wtype, updated)


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
    changes = [Change(n, before[n], v) for n, v in after.items() if before[n] != v]
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
            cat.lifecycle,
            updated.status,
            had_technician=had_technician,
            has_technician=technician_id is not None,
        )
        if move is not None:
            stamps = _snapshot(updated, STAMP_FIELDS)
            target = cat.lifecycle.target(updated.status, move, before_cancel=None)
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
