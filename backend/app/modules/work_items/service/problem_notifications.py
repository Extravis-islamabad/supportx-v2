"""Problem notifications: what the notification engine may know of a problem (WP-044c D15).

Registered through `app.shared.notifications.ports` like incidents (lane B, 2026-11-06): the
engine does rules, recipients, templates and channels; this source says which events notify,
who is relative to the problem, and who may see it. Problems are staff records only: requesters
never see one (D15, REQ-PRB-075), so no event is public and nobody gets a public side.

Appendix A (file 04) defaults:
- assigned to you (required) and investigator added;
- a known error published, and the problem solved: the technicians of the incidents it
  causes hear it, as they can now apply the workaround or close their incidents;
- the target date nearing and passed (the problems' SLA targets);
- mentions (required); private notes and closing, off by default.
"""

import html
import uuid
from collections.abc import Mapping

import nh3
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import NotFound
from app.modules import sla
from app.modules.identity_access import subject_for, user_names
from app.modules.organization import unit_heads, users_in_groups
from app.modules.work_items.domain.conversation import FollowReason
from app.modules.work_items.domain.lifecycle import WorkItemAction
from app.modules.work_items.domain.parts import LinkKind
from app.modules.work_items.domain.types import PROBLEM
from app.modules.work_items.events import (
    WorkItemAssigned,
    WorkItemConversationAdded,
    WorkItemCreated,
    WorkItemFollowerAdded,
    WorkItemStatusChanged,
    WorkItemUpdated,
)
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemConversation,
    WorkItemFollower,
    WorkItemLink,
)
from app.modules.work_items.service import catalogue
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.realtime import RECORD_KIND
from app.shared.events import EventEnvelope
from app.shared.notifications.ports import (
    EventDefault,
    LabelRef,
    Localised,
    NotificationCategory,
    NotificationEvent,
    RecordAccess,
    RecordContext,
    Variable,
    VariableValue,
    register_record_source,
)

EXCERPT = 500
# The technicians of the incidents this problem causes (D15).
LINKED_TECHNICIANS = "linked_incident_technicians"
_CONVERSATION = (
    Variable("conversation.author", "notification_variable.conversation.author"),
    Variable("conversation.excerpt", "notification_variable.conversation.excerpt"),
)
_SLA = (Variable("sla.target", "notification_variable.sla.target"),)
_STATUS_EVENTS: Mapping[str, str] = {
    WorkItemAction.RESOLVE: "problem.resolved",
    WorkItemAction.CLOSE: "problem.closed",
}
_SLA_EVENTS: Mapping[str, str] = {
    sla.SlaWarning.event_type: "problem.target_warning",
    sla.SlaBreached.event_type: "problem.target_breached",
}
_TYPED = frozenset(
    {
        WorkItemCreated.event_type,
        WorkItemAssigned.event_type,
        WorkItemStatusChanged.event_type,
        WorkItemUpdated.event_type,
    }
)

EVENTS: tuple[NotificationEvent, ...] = (
    NotificationEvent(
        "problem.created_in_group",
        NotificationCategory.CREATED,
        EventDefault(enabled=False, recipients=("group",)),
        public=False,
    ),
    NotificationEvent(
        "problem.assigned",
        NotificationCategory.ASSIGNMENT,
        EventDefault(enabled=True, recipients=("assignee",)),
        required=True,  # "assigned to me" (Appendix A)
        public=False,
    ),
    NotificationEvent(
        "problem.investigator_added",
        NotificationCategory.ASSIGNMENT,
        EventDefault(enabled=True, recipients=("new_investigator",)),
        public=False,
    ),
    NotificationEvent(
        "problem.known_error",
        NotificationCategory.STATUS,
        EventDefault(enabled=True, recipients=(LINKED_TECHNICIANS, "followers")),
        public=False,
    ),
    NotificationEvent(
        "problem.resolved",
        NotificationCategory.STATUS,
        EventDefault(enabled=True, recipients=(LINKED_TECHNICIANS, "followers")),
        public=False,
    ),
    NotificationEvent(
        "problem.closed",
        NotificationCategory.STATUS,
        EventDefault(enabled=False, recipients=("followers",)),
        public=False,
    ),
    NotificationEvent(
        "problem.target_warning",
        NotificationCategory.STATUS,
        EventDefault(enabled=True, recipients=("assignee",)),
        variables=_SLA,
        public=False,
    ),
    NotificationEvent(
        "problem.target_breached",
        NotificationCategory.STATUS,
        EventDefault(enabled=True, recipients=("assignee", "group_head")),
        variables=_SLA,
        public=False,
    ),
    NotificationEvent(
        "problem.note",
        NotificationCategory.CONVERSATION,
        EventDefault(enabled=False, recipients=("assignee", "followers")),
        variables=_CONVERSATION,
        public=False,
    ),
    NotificationEvent(
        "problem.mentioned",
        NotificationCategory.MENTION,
        EventDefault(enabled=True, recipients=("mentioned",)),
        required=True,
        variables=_CONVERSATION,
        public=False,
    ),
)

RECIPIENT_KINDS = (
    "assignee",
    "group",
    "group_head",
    "followers",
    "mentioned",
    "new_investigator",
    LINKED_TECHNICIANS,
)

VARIABLES = (
    Variable("record.display_id", "notification_variable.record.display_id"),
    Variable("record.title", "notification_variable.record.title"),
    Variable("record.priority", "notification_variable.record.priority"),
    Variable("record.status", "notification_variable.record.status"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("assignee.name", "notification_variable.assignee.name"),
    Variable("actor.name", "notification_variable.actor.name"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)


def _actor(envelope: EventEnvelope) -> uuid.UUID | None:
    if envelope.actor.type != "user":
        return None
    try:
        return uuid.UUID(envelope.actor.id)
    except ValueError:
        return None


def _excerpt(body: str) -> str:
    text = html.unescape(nh3.clean(body.replace("</p>", "</p>\n"), tags=set())).strip()
    return text if len(text) <= EXCERPT else text[: EXCERPT - 1].rstrip() + "…"


def _known_error_now(payload: Mapping[str, object]) -> bool:
    fields = payload.get("changed_fields") or []
    return isinstance(fields, list) and "known_error_at" in fields


async def _linked_technicians(session: AsyncSession, problem_id: uuid.UUID) -> frozenset[uuid.UUID]:
    """The technicians of the live incidents this problem causes."""
    rows = await session.scalars(
        select(WorkItem.technician_id)
        .join(WorkItemLink, WorkItemLink.source_id == WorkItem.id)
        .where(
            WorkItemLink.target_id == problem_id,
            WorkItemLink.kind == LinkKind.CAUSED_BY.value,
            WorkItemLink.deleted_at.is_(None),
            WorkItem.deleted_at.is_(None),
            WorkItem.technician_id.is_not(None),
        )
    )
    return frozenset(r for r in rows if r is not None)


async def _relatives(
    session: AsyncSession, record: WorkItem, event_code: str, envelope: EventEnvelope
) -> dict[str, frozenset[uuid.UUID]]:
    payload = envelope.payload
    relatives: dict[str, frozenset[uuid.UUID]] = {
        "assignee": frozenset({record.technician_id} if record.technician_id else ()),
    }
    if record.group_id is not None:
        relatives["group"] = frozenset(
            await session.scalars(users_in_groups(frozenset({record.group_id})))
        )
        lead, head = await unit_heads(session, record.group_id, record.department_id)
        relatives["group_head"] = frozenset(p for p in (lead, head) if p is not None)
    relatives["followers"] = frozenset(
        await session.scalars(
            select(WorkItemFollower.user_id).where(
                WorkItemFollower.work_item_id == record.id, WorkItemFollower.deleted_at.is_(None)
            )
        )
    )
    if envelope.event_type == WorkItemCreated.event_type and event_code == "problem.assigned":
        relatives["assignee"] = frozenset({uuid.UUID(str(payload["technician_id"]))})
    if envelope.event_type == WorkItemFollowerAdded.event_type:
        relatives["new_investigator"] = frozenset({uuid.UUID(str(payload["user_id"]))})
    if event_code == "problem.mentioned":
        relatives["mentioned"] = frozenset(uuid.UUID(str(u)) for u in payload["mentioned_ids"])
    if event_code in {"problem.known_error", "problem.resolved"}:
        relatives[LINKED_TECHNICIANS] = await _linked_technicians(session, record.id)
    return relatives


class ProblemNotifications:
    """`RecordSource` for problems."""

    record_type = "problem"
    channel_kind = RECORD_KIND
    events = EVENTS
    recipient_kinds = RECIPIENT_KINDS
    variables = VARIABLES
    conditions = ("priority", "status_category")
    event_types = (
        WorkItemCreated.event_type,
        WorkItemAssigned.event_type,
        WorkItemUpdated.event_type,
        WorkItemConversationAdded.event_type,
        WorkItemStatusChanged.event_type,
        WorkItemFollowerAdded.event_type,
        *_SLA_EVENTS,
    )

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:  # noqa: PLR0911 - one return per event family, flat
        """Notification events of one committed work item event (problems only)."""
        payload = envelope.payload
        kind = envelope.event_type
        if kind in _SLA_EVENTS:
            return (_SLA_EVENTS[kind],) if payload.get("record_type") == PROBLEM.code.value else ()
        if kind in _TYPED and payload.get("type") != PROBLEM.code.value:
            return ()
        if kind == WorkItemCreated.event_type:
            assigned = ("problem.assigned",) if payload.get("technician_id") else ()
            return ("problem.created_in_group", *assigned)
        if kind == WorkItemAssigned.event_type:
            return ("problem.assigned",) if payload.get("technician_id") else ()
        if kind == WorkItemUpdated.event_type:
            # Marked a known error (REQ-PRB-036); `context` checks it is live, not retired.
            return ("problem.known_error",) if _known_error_now(payload) else ()
        if kind == WorkItemStatusChanged.event_type:
            found = _STATUS_EVENTS.get(str(payload["action"]))
            return (found,) if found else ()
        # Untyped events: `context` returns None unless the record is a problem.
        if kind == WorkItemFollowerAdded.event_type:
            investigator = payload.get("reason") == FollowReason.INVESTIGATOR.value
            return ("problem.investigator_added",) if investigator else ()
        if payload.get("automatic"):
            return ()
        return ("problem.mentioned",) if payload.get("mentioned_ids") else ("problem.note",)

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The problem as it is now, with the people relative to it for this event."""
        payload = envelope.payload
        record_id = uuid.UUID(str(payload.get("work_item_id") or payload["record_id"]))
        record = await session.scalar(
            select(WorkItem).where(WorkItem.id == record_id, WorkItem.deleted_at.is_(None))
        )
        if record is None or record.type != PROBLEM.code.value:
            return None
        if event_code == "problem.known_error" and (
            record.known_error_at is None or record.known_error_retired_at is not None
        ):
            return None  # the flag was removed or retired: nothing to tell
        actor = _actor(envelope)
        people = [p for p in (record.technician_id, actor) if p is not None]
        names = await user_names(session, [str(p) for p in people])
        cat = await catalogue.load(session, PROBLEM)
        status = next((s for s in cat.statuses if s.code == record.status), None)
        shared: dict[str, VariableValue] = {
            "record.display_id": record.display_id,
            "record.title": record.subject,
            "record.priority": LabelRef(f"priority.{record.priority}"),
            "record.status": Localised(
                (status.labels or {}) if status else {},
                fallback=f"work_item_status.{record.status}",
            ),
            "record.link": f"/problems/{record.id}",
            "assignee.name": names.get(str(record.technician_id)) if record.technician_id else None,
            "actor.name": names.get(str(actor)) if actor else None,
        }
        if envelope.event_type in _SLA_EVENTS:
            shared["sla.target"] = LabelRef(f"sla_target_kind.{payload['kind']}")
        if envelope.event_type == WorkItemConversationAdded.event_type:
            entry = await session.scalar(
                select(WorkItemConversation).where(
                    WorkItemConversation.id == uuid.UUID(str(payload["entry_id"])),
                    WorkItemConversation.deleted_at.is_(None),
                )
            )
            if entry is None:
                return None
            shared["conversation.author"] = shared["actor.name"]
            shared["conversation.excerpt"] = _excerpt(entry.body)
        return RecordContext(
            record_id=record.id,
            display_id=record.display_id,
            link=f"/problems/{record.id}",
            variables=shared,
            public_variables={},
            relatives=await _relatives(session, record, event_code, envelope),
            conditions={"priority": record.priority, "status_category": record.status_category},
            urgent=envelope.event_type in _SLA_EVENTS,
            event_code=event_code,
            entry_id=uuid.UUID(str(payload["entry_id"])) if "entry_id" in payload else None,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for whoever may see the problem; NONE otherwise (never a public side)."""
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        subject = await subject_for(session, tenant, user_id)
        try:
            await items.visible_record(session, subject, PROBLEM, record_id)
        except NotFound:
            return RecordAccess.NONE
        return RecordAccess.FULL


SOURCE = ProblemNotifications()


def register() -> None:
    """Make problems notify (idempotent; called when work_items is imported)."""
    register_record_source(SOURCE)
