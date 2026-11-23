"""Personal reminder alerts (WP-046a S2; REQ-INC-082 AC1): its owner, and nobody else.

One record source (record type `reminder`) for reminders on every work item type. Its only
recipient is the reminder's owner. At send time the reminder is read again: completed, removed,
moved to another time, or on a record its owner can no longer see, nothing is sent (the
coordinator); the delivery log says why.
"""

import uuid
from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import NotFound, PermissionDenied
from app.modules.identity_access import subject_for
from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.events import WorkItemReminderDue
from app.modules.work_items.infra.models import WorkItem, WorkItemReminder
from app.modules.work_items.service import work_items as items
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

RECORD_TYPE = "reminder"
OWNER = "owner"
DUE = "reminder.due"

VARIABLES = (
    Variable("reminder.note", "notification_variable.reminder.note"),
    Variable("reminder.at", "notification_variable.reminder.at"),
    Variable("record.display_id", "notification_variable.record.display_id"),
    Variable("record.title", "notification_variable.record.title"),
    Variable("record.link", "notification_variable.record.link"),
)
EVENTS = (
    NotificationEvent(
        DUE,
        NotificationCategory.ASSIGNMENT,
        EventDefault(enabled=True, recipients=(OWNER,)),
        required=True,  # the person set it for themselves
    ),
)


class ReminderNotifications:
    """`RecordSource` for personal reminders."""

    record_type = RECORD_TYPE
    channel_kind = RECORD_KIND
    events = EVENTS
    recipient_kinds = (OWNER,)
    variables = VARIABLES
    conditions = ("record_type",)
    event_types = (WorkItemReminderDue.event_type,)

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """The alert of one committed event."""
        return (DUE,) if envelope.event_type == WorkItemReminderDue.event_type else ()

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The reminder and its record as they are now; None when it no longer stands."""
        payload = envelope.payload
        row = await session.scalar(
            select(WorkItemReminder).where(
                WorkItemReminder.id == uuid.UUID(str(payload["reminder_id"])),
                WorkItemReminder.deleted_at.is_(None),
                WorkItemReminder.done_at.is_(None),
            )
        )
        record = await session.scalar(
            select(WorkItem).where(
                WorkItem.id == uuid.UUID(str(payload["work_item_id"])),
                WorkItem.deleted_at.is_(None),
            )
        )
        if row is None or record is None or row.remind_at.isoformat() != _iso(payload):
            return None
        wtype = TYPES[WorkItemTypeCode(record.type)]
        link = f"/{wtype.path}/{record.id}"
        values: dict[str, VariableValue] = {
            "reminder.note": row.note,
            "reminder.at": row.remind_at,
            "record.display_id": record.display_id,
            "record.title": record.subject,
            "record.link": link,
        }
        return RecordContext(
            record_id=record.id,
            display_id=record.display_id,
            link=link,
            variables=values,
            public_variables={},  # never a public reader: the owner sees it in full or not at all
            relatives={OWNER: frozenset({row.user_id})},
            conditions={"record_type": record.type},
            urgent=True,  # the person chose this time; never held for a digest
            event_code=event_code,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL while the owner can see the record; otherwise nothing (no alert)."""
        record = await session.get(WorkItem, record_id)
        if record is None or record.deleted_at is not None:
            return RecordAccess.NONE
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        subject = await subject_for(session, tenant, user_id)
        try:
            await items.visible_record(
                session, subject, TYPES[WorkItemTypeCode(record.type)], record_id
            )
        except (NotFound, PermissionDenied):
            return RecordAccess.NONE
        return RecordAccess.FULL


def _iso(payload: Mapping[str, object]) -> str:
    return datetime.fromisoformat(str(payload["remind_at"])).isoformat()


SOURCE = ReminderNotifications()


def register() -> None:
    """Make personal reminders notify (idempotent; called when work_items is imported)."""
    register_record_source(SOURCE)


__all__ = ["SOURCE", "register"]
