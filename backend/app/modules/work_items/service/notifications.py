"""Incident notifications: what the notification engine may know of an incident (WP-023).

Registered through `app.shared.notifications.ports` (agreed with lane A, 2026-10-28); the
engine in the notifications module does rules, recipients, templates and channels. Everything
here follows the work items' own rules:

- which events notify: REQ-INC-130 and file 01 Appendix A (D-041) for the defaults;
- who may see what, at send time: `visible_record` (group scope D-052, the hand-over rule) and
  `sees_private` (staff), the same checks as the record page and its files (REQ-NTF-010);
- requesters and anyone who may not see private notes get `public_variables`: a private note's
  text is never among them.

A public **reply** is itself the message to the requester (sent by the e-mail channel, WP-024),
so its notification reaches the requester in-app and followers by e-mail, never a second e-mail
to the requester; a public **note** has no message of its own and notifies the requester on both
channels.
"""

import html
import uuid
from collections.abc import Mapping

import nh3
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import NotFound
from app.modules.identity_access import subject_for, user_names
from app.modules.organization import unit_heads, users_in_groups
from app.modules.work_items.domain.conversation import EntryKind, Visibility
from app.modules.work_items.domain.lifecycle import WorkItemAction
from app.modules.work_items.domain.types import INCIDENT
from app.modules.work_items.events import (
    WorkItemAssigned,
    WorkItemConversationAdded,
    WorkItemCreated,
    WorkItemFollowerAdded,
    WorkItemStatusChanged,
)
from app.modules.work_items.infra.models import WorkItem, WorkItemConversation, WorkItemFollower
from app.modules.work_items.service import catalogue
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.file_access import sees_private
from app.modules.work_items.service.realtime import RECORD_KIND
from app.shared.events import EventEnvelope
from app.shared.notifications.ports import (
    EventDefault,
    LabelRef,
    Localised,
    NotificationCategory,
    NotificationChannel,
    NotificationEvent,
    RecordAccess,
    RecordContext,
    Variable,
    VariableValue,
    register_record_source,
)

IN_APP = (NotificationChannel.IN_APP,)
BOTH = (NotificationChannel.IN_APP, NotificationChannel.EMAIL)
EXCERPT = 500  # characters of a reply or note shown in a notification

_STATUS_EVENTS: Mapping[str, str] = {
    WorkItemAction.RESOLVE: "incident.resolved",
    WorkItemAction.CLOSE: "incident.closed",
    WorkItemAction.REOPEN: "incident.reopened",
    WorkItemAction.CANCEL: "incident.canceled",
}
# Events that say which work item type they are about.
_TYPED = frozenset(
    {WorkItemCreated.event_type, WorkItemAssigned.event_type, WorkItemStatusChanged.event_type}
)
_QUIET_ACTIONS = frozenset({WorkItemAction.ASSIGN, WorkItemAction.UNASSIGN})

_CONVERSATION = (
    Variable("conversation.author", "notification_variable.conversation.author"),
    Variable("conversation.excerpt", "notification_variable.conversation.excerpt"),
)
_STATUS_CHANGE = (Variable("change.from_status", "notification_variable.change.from_status"),)

EVENTS: tuple[NotificationEvent, ...] = (
    NotificationEvent(
        "incident.created",
        NotificationCategory.CREATED,
        EventDefault(enabled=True, recipients=("requester",)),
    ),
    NotificationEvent(
        "incident.created_in_group",
        NotificationCategory.CREATED,
        EventDefault(enabled=False, recipients=("group",)),
    ),
    NotificationEvent(
        "incident.assigned",
        NotificationCategory.ASSIGNMENT,
        EventDefault(enabled=True, recipients=("assignee",)),
        required=True,  # "assigned to me" (Appendix A, file 03)
    ),
    NotificationEvent(
        "incident.public_reply",
        NotificationCategory.CONVERSATION,
        EventDefault(enabled=True, recipients=("requester", "followers")),
        variables=_CONVERSATION,
    ),
    NotificationEvent(
        "incident.public_note",
        NotificationCategory.CONVERSATION,
        EventDefault(enabled=True, recipients=("requester", "followers")),
        variables=_CONVERSATION,
    ),
    NotificationEvent(
        "incident.private_note",
        NotificationCategory.CONVERSATION,
        EventDefault(enabled=False, recipients=("assignee", "followers")),
        variables=_CONVERSATION,
        public=False,
    ),
    NotificationEvent(
        "incident.requester_replied",
        NotificationCategory.CONVERSATION,
        EventDefault(enabled=True, recipients=("assignee",)),
        variables=_CONVERSATION,
    ),
    NotificationEvent(
        "incident.mentioned",
        NotificationCategory.MENTION,
        EventDefault(enabled=True, recipients=("mentioned",)),
        required=True,
        variables=_CONVERSATION,
    ),
    NotificationEvent(
        "incident.status_changed",
        NotificationCategory.STATUS,
        EventDefault(enabled=False, recipients=("requester",)),
        variables=_STATUS_CHANGE,
    ),
    NotificationEvent(
        "incident.resolved",
        NotificationCategory.STATUS,
        EventDefault(enabled=True, recipients=("requester",)),
    ),
    NotificationEvent(
        "incident.closed",
        NotificationCategory.STATUS,
        EventDefault(enabled=False, recipients=("requester",)),
    ),
    NotificationEvent(
        "incident.reopened",
        NotificationCategory.STATUS,
        EventDefault(enabled=True, recipients=("assignee",)),
    ),
    NotificationEvent(
        "incident.canceled",
        NotificationCategory.STATUS,
        EventDefault(enabled=False, recipients=("requester",)),
    ),
    NotificationEvent(
        "incident.follower_added",
        NotificationCategory.FOLLOWING,
        EventDefault(enabled=False, recipients=("new_follower",), channels=IN_APP),
    ),
)

RECIPIENT_KINDS = (
    "requester",
    "on_behalf_of",
    "assignee",
    "previous_assignee",
    "group",
    "group_head",
    "followers",
    "mentioned",
    "new_follower",
)

VARIABLES = (
    Variable("record.display_id", "notification_variable.record.display_id"),
    Variable("record.title", "notification_variable.record.title"),
    Variable("record.priority", "notification_variable.record.priority"),
    Variable("record.status", "notification_variable.record.status"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("requester.name", "notification_variable.requester.name"),
    Variable("assignee.name", "notification_variable.assignee.name"),
    Variable("actor.name", "notification_variable.actor.name"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)


def _uuid(value: object) -> uuid.UUID | None:
    return uuid.UUID(str(value)) if value else None


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


def _conversation_events(payload: Mapping[str, object]) -> tuple[str, ...]:
    if payload.get("kind") == EntryKind.NOTE:
        private = payload.get("visibility") == Visibility.PRIVATE
        codes = ["incident.private_note" if private else "incident.public_note"]
    else:
        codes = ["incident.public_reply"]
    if payload.get("mentioned_ids"):
        codes.append("incident.mentioned")
    return tuple(codes)


class IncidentNotifications:
    """`RecordSource` for incidents."""

    record_type = "incident"
    channel_kind = RECORD_KIND
    events = EVENTS
    recipient_kinds = RECIPIENT_KINDS
    variables = VARIABLES
    conditions = ("priority", "status_category", "channel")
    event_types = (
        WorkItemCreated.event_type,
        WorkItemAssigned.event_type,
        WorkItemConversationAdded.event_type,
        WorkItemStatusChanged.event_type,
        WorkItemFollowerAdded.event_type,
    )

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """Notification events of one committed work item event (incidents only)."""
        payload = envelope.payload
        kind = envelope.event_type
        if kind in _TYPED and payload.get("type") != INCIDENT.code.value:
            return ()
        if kind == WorkItemCreated.event_type:
            # Created already assigned: the technician hears it like any assignment.
            assigned = ("incident.assigned",) if payload.get("technician_id") else ()
            return ("incident.created", "incident.created_in_group", *assigned)
        if kind == WorkItemAssigned.event_type:
            return ("incident.assigned",) if payload.get("technician_id") else ()
        if kind == WorkItemStatusChanged.event_type:
            action = payload["action"]
            quiet = action in _QUIET_ACTIONS
            return () if quiet else (_STATUS_EVENTS.get(action, "incident.status_changed"),)
        # Conversation and follower events carry no type: incidents are the only work items now;
        # `context` returns None for a record of another type.
        if kind == WorkItemFollowerAdded.event_type:
            return ("incident.follower_added",)
        return _conversation_events(payload)

    async def context(  # noqa: C901 - one block per event family, flat
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The incident as it is now, with the people relative to it for this event."""
        payload = envelope.payload
        record_id = uuid.UUID(str(payload["work_item_id"]))
        record = await session.scalar(
            select(WorkItem).where(WorkItem.id == record_id, WorkItem.deleted_at.is_(None))
        )
        if record is None or record.type != INCIDENT.code.value:
            return None
        actor = _actor(envelope)
        if event_code == "incident.requester_replied" or (
            event_code == "incident.public_reply" and actor == record.requester_id
        ):
            # A reply by the requester (portal, e-mail) tells the assignee instead.
            event_code = "incident.requester_replied"
        relatives: dict[str, frozenset[uuid.UUID]] = {
            "requester": frozenset({record.requester_id}),
            "on_behalf_of": frozenset({record.on_behalf_of_id} if record.on_behalf_of_id else ()),
            "assignee": frozenset({record.technician_id} if record.technician_id else ()),
        }
        if record.group_id is not None:
            members = await session.scalars(users_in_groups(frozenset({record.group_id})))
            relatives["group"] = frozenset(members)
            lead, head = await unit_heads(session, record.group_id, record.department_id)
            relatives["group_head"] = frozenset(p for p in (lead, head) if p is not None)
        followers = await session.scalars(
            select(WorkItemFollower.user_id).where(
                WorkItemFollower.work_item_id == record.id, WorkItemFollower.deleted_at.is_(None)
            )
        )
        relatives["followers"] = frozenset(followers)
        if envelope.event_type == WorkItemCreated.event_type and event_code == "incident.assigned":
            # The technician of the creation, even if someone else holds it by now (their own
            # assignment event tells them).
            relatives["assignee"] = frozenset({uuid.UUID(str(payload["technician_id"]))})
        if envelope.event_type == WorkItemAssigned.event_type:
            before = _uuid((payload.get("audience_before") or {}).get("technician_id"))
            if before is not None and before != record.technician_id:
                relatives["previous_assignee"] = frozenset({before})
        if envelope.event_type == WorkItemFollowerAdded.event_type:
            relatives["new_follower"] = frozenset({uuid.UUID(str(payload["user_id"]))})
        if event_code == "incident.mentioned":
            relatives["mentioned"] = frozenset(uuid.UUID(str(u)) for u in payload["mentioned_ids"])

        people = [p for p in (record.requester_id, record.technician_id, actor) if p is not None]
        names = await user_names(session, [str(p) for p in people])
        cat = await catalogue.load(session, INCIDENT)
        status = next((s for s in cat.statuses if s.code == record.status), None)

        def status_value(code: str | None) -> VariableValue:
            found = next((s for s in cat.statuses if s.code == code), None)
            if code is None:
                return None
            return Localised(
                found.labels or {} if found else {}, fallback=f"work_item_status.{code}"
            )

        shared: dict[str, VariableValue] = {
            "record.display_id": record.display_id,
            "record.title": record.subject,
            "record.priority": LabelRef(f"priority.{record.priority}"),
            "record.status": status_value(status.code if status else record.status),
            "record.link": f"/incidents/{record.id}",
            "requester.name": names.get(str(record.requester_id)),
            "assignee.name": names.get(str(record.technician_id)) if record.technician_id else None,
            "actor.name": names.get(str(actor)) if actor else None,
        }
        if envelope.event_type == WorkItemStatusChanged.event_type:
            shared["change.from_status"] = status_value(payload.get("from_status"))
        full = dict(shared)
        public = dict(shared)
        if envelope.event_type == WorkItemConversationAdded.event_type:
            entry = await session.scalar(
                select(WorkItemConversation).where(
                    WorkItemConversation.id == uuid.UUID(str(payload["entry_id"])),
                    WorkItemConversation.deleted_at.is_(None),
                )
            )
            if entry is None:
                return None
            full["conversation.author"] = shared["actor.name"]
            full["conversation.excerpt"] = _excerpt(entry.body)
            if entry.visibility == Visibility.PUBLIC.value:
                public["conversation.author"] = shared["actor.name"]
                public["conversation.excerpt"] = full["conversation.excerpt"]
        return RecordContext(
            record_id=record.id,
            display_id=record.display_id,
            link=f"/incidents/{record.id}",
            variables=full,
            public_variables=public,
            relatives=relatives,
            conditions={
                "priority": record.priority,
                "status_category": record.status_category,
                "channel": record.channel,
            },
            urgent=record.priority == "p1",
            event_code=event_code,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for staff who may see the incident, PUBLIC for requesters, NONE otherwise.

        The incident's own requester (and the person it is for) always sees its public side,
        as the portal will show it (WP-028), even without a console permission.
        """
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        subject = await subject_for(session, tenant, user_id)
        try:
            await items.visible_record(session, subject, INCIDENT, record_id)
        except NotFound:
            people = (
                await session.execute(
                    select(WorkItem.requester_id, WorkItem.on_behalf_of_id).where(
                        WorkItem.id == record_id, WorkItem.deleted_at.is_(None)
                    )
                )
            ).first()
            own = people is not None and user_id in (people.requester_id, people.on_behalf_of_id)
            return RecordAccess.PUBLIC if own else RecordAccess.NONE
        return RecordAccess.FULL if sees_private(subject, INCIDENT) else RecordAccess.PUBLIC


SOURCE = IncidentNotifications()


def register() -> None:
    """Make incidents notify (idempotent; called when work_items is imported)."""
    register_record_source(SOURCE)
