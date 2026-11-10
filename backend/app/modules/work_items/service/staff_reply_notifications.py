"""Replies on changes and releases (the coordinator, 2026-11-11; lane B's #359).

Changes and releases are staff records: their replies are not e-mailed to the requester by
default. Each type has a reply notice in the notification rules, OFF by default, so a reply
never hangs in "queued": no requester e-mail is made for it, and the engine marks it not
e-mailed at once (#359's settle step). Turning it on is configuration, not code (Haider is
asked; the coordinator parked the question). WP-056 may give these types richer sources; this
one only carries their replies.
"""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import NotFound
from app.modules.identity_access import subject_for, user_names
from app.modules.work_items.domain.conversation import EntryKind
from app.modules.work_items.domain.types import TYPES, WorkItemType, WorkItemTypeCode
from app.modules.work_items.events import WorkItemConversationAdded
from app.modules.work_items.infra.models import WorkItem, WorkItemConversation
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.file_access import sees_private
from app.modules.work_items.service.notifications import move_reply_delivery, reply_excerpt
from app.modules.work_items.service.realtime import RECORD_KIND
from app.shared.events import EventEnvelope
from app.shared.notifications.ports import (
    EventDefault,
    NotificationCategory,
    NotificationEvent,
    RecordAccess,
    RecordContext,
    Variable,
    VariableValue,
    register_record_source,
)

REQUESTER = "requester"  # the requester and the person it is for
_LINKS = {WorkItemTypeCode.CHANGE: "/changes/", WorkItemTypeCode.RELEASE: "/releases/"}
VARIABLES = (
    Variable("record.display_id", "notification_variable.record.display_id"),
    Variable("record.title", "notification_variable.record.title"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("recipient.name", "notification_variable.recipient.name"),
    Variable("conversation.author", "notification_variable.conversation.author"),
    Variable("conversation.excerpt", "notification_variable.conversation.excerpt"),
)


class StaffReplyNotifications:
    """`RecordSource` for one staff record type's replies (changes, releases)."""

    recipient_kinds = (REQUESTER,)
    variables = VARIABLES
    conditions: tuple[str, ...] = ()
    channel_kind = RECORD_KIND
    event_types = (WorkItemConversationAdded.event_type,)

    def __init__(self, wtype: WorkItemType) -> None:
        self._wtype = wtype
        self.record_type = wtype.code.value
        self.reply = f"{wtype.code.value}.public_reply"
        self.events = (
            NotificationEvent(
                self.reply,
                NotificationCategory.CONVERSATION,
                # Off: a staff record's reply is not e-mailed unless the tenant turns it on.
                EventDefault(enabled=False, recipients=(REQUESTER,)),
            ),
        )

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """A reply (no type on the event: `context` answers only for this type)."""
        payload = envelope.payload
        if payload.get("automatic") or payload.get("kind") != EntryKind.REPLY:
            return ()
        return (self.reply,)

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The reply on a record of this type, for its requester."""
        del event_code
        payload = envelope.payload
        record = await session.get(WorkItem, uuid.UUID(str(payload["work_item_id"])))
        if record is None or record.deleted_at is not None or record.type != self.record_type:
            return None
        entry = await session.get(WorkItemConversation, uuid.UUID(str(payload["entry_id"])))
        if entry is None or entry.deleted_at is not None or entry.kind != EntryKind.REPLY:
            return None
        people = frozenset(
            p for p in (record.requester_id, record.on_behalf_of_id) if p is not None
        )
        author = str(entry.created_by) if entry.created_by else None
        names = await user_names(session, [author] if author else [])
        link = f"{_LINKS[self._wtype.code]}{record.id}"
        variables: dict[str, VariableValue] = {
            "record.display_id": record.display_id,
            "record.title": record.subject,
            "record.link": link,
            "conversation.author": names.get(author) if author else None,
            "conversation.excerpt": reply_excerpt(entry.body),
        }
        return RecordContext(
            record_id=record.id,
            display_id=record.display_id,
            link=link,
            public_link=None,
            variables=variables,
            public_variables=variables,
            relatives={REQUESTER: people},
            conditions={},
            event_code=self.reply,
            entry_id=entry.id,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """Staff who see the record in full; its requester its public side."""
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        subject = await subject_for(session, tenant, user_id)
        try:
            await items.visible_record(session, subject, self._wtype, record_id)
        except NotFound:
            record = await session.get(WorkItem, record_id)
            if record is not None and user_id in {record.requester_id, record.on_behalf_of_id}:
                return RecordAccess.PUBLIC
            return RecordAccess.NONE
        return RecordAccess.FULL if sees_private(subject, self._wtype) else RecordAccess.PUBLIC

    async def delivery_changed(  # noqa: PLR0913 - the port's fields, explicit
        self,
        session: AsyncSession,
        *,
        record_id: uuid.UUID,
        entry_id: uuid.UUID,
        state: str,
        reason: str | None,
        at: datetime,
    ) -> None:
        """The reply follows its e-mail, or its settling when none was made (#359)."""
        await move_reply_delivery(
            session, record_id=record_id, entry_id=entry_id, state=state, reason=reason, at=at
        )


SOURCES = tuple(
    StaffReplyNotifications(TYPES[code])
    for code in (WorkItemTypeCode.CHANGE, WorkItemTypeCode.RELEASE)
    if code in TYPES
)


def register() -> None:
    """Make change and release replies settle (idempotent; called when work_items is imported)."""
    for source in SOURCES:
        register_record_source(source)
