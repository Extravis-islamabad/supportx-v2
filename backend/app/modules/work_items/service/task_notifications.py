"""Task notifications (WP-046a S1; REQ-INC-073 AC2, -076): what the engine may know of a task.

One record source for tasks on every work item type (record type `task`): its owner hears that
a task was given to them, that its scheduled start is near (its own reminder), and that it is
overdue. The record a task belongs to is the context: its number and subject, as the owner's "my
tasks" shows them.

Access follows the task's record at send time. Someone who may see the record gets it in full
(its link); a task-only owner (the type lets owners work without access, D-112) gets the public
side: the task, the record's number and subject, and the link to their tasks, never the
record's page. Anyone else gets nothing. A reminder is re-read at send time: done, canceled,
removed, given to someone else, or moved to another time, it says nothing.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import NotFound, PermissionDenied
from app.modules.identity_access import subject_for, user_names
from app.modules.work_items.domain.parts import OPEN_TASK_STATUSES
from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.events import WorkItemTaskAssigned, WorkItemTaskReminderDue
from app.modules.work_items.infra.models import WorkItem, WorkItemTask
from app.modules.work_items.service import parts
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.realtime import RECORD_KIND
from app.modules.work_items.service.task_reminders import OVERDUE, STARTS_SOON
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

RECORD_TYPE = "task"
OWNER = "owner"
ASSIGNED = "task.assigned"
STARTS = "task.starts_soon"
LATE = "task.overdue"
_REMINDERS = {STARTS_SOON: STARTS, OVERDUE: LATE}
MY_TASKS = "/my-tasks"

VARIABLES = (
    Variable("task.title", "notification_variable.task.title"),
    Variable("task.starts_at", "notification_variable.task.starts_at"),
    Variable("task.due_at", "notification_variable.task.due_at"),
    Variable("record.display_id", "notification_variable.record.display_id"),
    Variable("record.title", "notification_variable.record.title"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("actor.name", "notification_variable.actor.name"),
)
EVENTS = (
    NotificationEvent(
        ASSIGNED,
        NotificationCategory.ASSIGNMENT,
        EventDefault(enabled=True, recipients=(OWNER,)),
        required=True,  # "assigned to me" (Appendix A): never switched off
    ),
    NotificationEvent(
        STARTS,
        NotificationCategory.ASSIGNMENT,
        EventDefault(enabled=True, recipients=(OWNER,)),
    ),
    NotificationEvent(
        LATE,
        NotificationCategory.ASSIGNMENT,
        EventDefault(enabled=True, recipients=(OWNER,)),
    ),
)


def _when(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value else None


def _stands(task: WorkItemTask, envelope: EventEnvelope) -> bool:
    """The event still fits the task as it is now (never for a moved time or another owner)."""
    payload = envelope.payload
    if envelope.event_type == WorkItemTaskAssigned.event_type:
        return str(task.owner_id) == str(payload["owner_id"])
    if task.status not in OPEN_TASK_STATUSES or task.owner_id is None:
        return False
    claimed = _when(payload.get("at"))
    current = task.scheduled_start if payload.get("kind") == STARTS_SOON else task.due_at
    return claimed is not None and current == claimed


class TaskNotifications:
    """`RecordSource` for tasks on every work item type."""

    record_type = RECORD_TYPE
    channel_kind = RECORD_KIND
    events = EVENTS
    recipient_kinds = (OWNER,)
    variables = VARIABLES
    conditions = ("record_type",)
    event_types = (WorkItemTaskAssigned.event_type, WorkItemTaskReminderDue.event_type)

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """Notification events of one committed event."""
        if envelope.event_type == WorkItemTaskAssigned.event_type:
            return (ASSIGNED,)
        if envelope.event_type == WorkItemTaskReminderDue.event_type:
            found = _REMINDERS.get(str(envelope.payload.get("kind")))
            return (found,) if found else ()
        return ()

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The task and its record as they are now; None when either is gone or it moved."""
        payload = envelope.payload
        task = await session.scalar(
            select(WorkItemTask).where(
                WorkItemTask.id == uuid.UUID(str(payload["task_id"])),
                WorkItemTask.deleted_at.is_(None),
            )
        )
        record = await session.scalar(
            select(WorkItem).where(
                WorkItem.id == uuid.UUID(str(payload["work_item_id"])),
                WorkItem.deleted_at.is_(None),
            )
        )
        if task is None or record is None or task.owner_id is None or not _stands(task, envelope):
            return None
        wtype = TYPES[WorkItemTypeCode(record.type)]
        actor = envelope.actor.id if envelope.actor.type == "user" else None
        names = await user_names(session, [actor] if actor else [])
        public: dict[str, VariableValue] = {
            "task.title": task.title,
            "task.starts_at": task.scheduled_start,
            "task.due_at": task.due_at,
            "record.display_id": record.display_id,
            "record.title": record.subject,
            "actor.name": names.get(actor) if actor else None,
        }
        link = f"/{wtype.path}/{record.id}"
        return RecordContext(
            record_id=record.id,
            display_id=record.display_id,
            link=link,
            variables={**public, "record.link": link},
            public_variables={**public, "record.link": MY_TASKS},
            relatives={OWNER: frozenset({task.owner_id})},
            conditions={"record_type": record.type},
            event_code=event_code,
            public_link=MY_TASKS,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """FULL for who may see the record; PUBLIC for a task-only owner; else nothing."""
        record = await session.get(WorkItem, record_id)
        if record is None or record.deleted_at is not None:
            return RecordAccess.NONE
        wtype = TYPES[WorkItemTypeCode(record.type)]
        tenant = session.info[SESSION_TENANT_KEY].tenant_id
        subject = await subject_for(session, tenant, user_id)
        try:
            await items.visible_record(session, subject, wtype, record_id)
        except (NotFound, PermissionDenied):
            owns = await session.scalar(
                select(WorkItemTask.id).where(
                    WorkItemTask.work_item_id == record_id,
                    WorkItemTask.owner_id == user_id,
                    WorkItemTask.deleted_at.is_(None),
                )
            )
            if owns is not None and await parts.owner_access(session, wtype):
                return RecordAccess.PUBLIC
            return RecordAccess.NONE
        return RecordAccess.FULL


SOURCE = TaskNotifications()


def register() -> None:
    """Make tasks notify (idempotent; called when work_items is imported)."""
    register_record_source(SOURCE)


__all__ = ["SOURCE", "register"]
