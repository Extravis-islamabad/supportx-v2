"""Personal reminders on work items (WP-046a S2; REQ-INC-082).

A reminder is its owner's alone: a note, when, and how long before to alert them. Nobody else
sees it, administrators included (AC2, the coordinator): every read and change is by the owner,
and anyone else gets "not found". Setting one needs only to see the record. It can be completed
(it leaves the open list and stays on the record as done, AC3), reopened and deleted.

A five-minute sweep raises each alert once, at its time minus its lead (AC1; times are stored in
UTC, so 15:00 with a 15-minute lead alerts at 14:45 wherever its owner is). If the owner can no
longer see the record, no alert is sent and the reminder reads "no longer available".
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import FieldError, NotFound, PermissionDenied, ValidationFailed
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.identity_access import Subject
from app.modules.work_items.domain.types import TYPES, WorkItemType, WorkItemTypeCode
from app.modules.work_items.events import WorkItemPartChangedV3, WorkItemReminderDue
from app.modules.work_items.infra.models import WorkItem, WorkItemReminder
from app.modules.work_items.service import work_items as items
from app.shared.clock import Clock, SystemClock
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Source

log = get_logger(__name__)

NOTE_MAX = 500
ALERT_MAX = 7 * 24 * 60
EVERY_SECONDS = 300
LOOK_BACK = timedelta(days=3)  # an alert missed longer ago is not sent late
MAX_OPEN = 500  # one person's open reminders


class ReminderRepository(Repository[WorkItemReminder]):
    """Reminders of the session's tenant."""

    model = WorkItemReminder


@dataclass(frozen=True)
class ReminderView:
    """A reminder with its record as its owner may see it now."""

    reminder: WorkItemReminder
    record_type: str
    display_id: str | None  # None: no longer available to its owner
    subject: str | None


def _problems(problems: list[tuple[str, str]]) -> ValidationFailed:
    return ValidationFailed(
        errors=[FieldError(field=f, code=c, message_key=f"errors.field.{c}") for f, c in problems]
    )


def _clean(values: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    problems: list[tuple[str, str]] = []
    clean: dict[str, Any] = {}
    if "note" in values or creating:
        note = " ".join(str(values.get("note") or "").split())
        if not note:
            problems.append(("note", "required"))
        elif len(note) > NOTE_MAX:
            problems.append(("note", "value_too_long"))
        clean["note"] = note
    if "remind_at" in values or creating:
        if not isinstance(values.get("remind_at"), datetime):
            problems.append(("remind_at", "required"))
        clean["remind_at"] = values.get("remind_at")
    if "alert_minutes" in values:
        minutes = values["alert_minutes"]
        if not isinstance(minutes, int) or not 0 <= minutes <= ALERT_MAX:
            problems.append(("alert_minutes", "out_of_range"))
        clean["alert_minutes"] = minutes
    if problems:
        raise _problems(problems)
    if "remind_at" in clean or "alert_minutes" in clean:
        clean["alerted_at"] = None  # a new time alerts again
    return clean


async def _signal(
    session: AsyncSession,
    row: WorkItemReminder,
    change: Literal["added", "changed", "removed"],
) -> None:
    """The owner's screens refresh; realtime tells their personal channel only."""
    await record_event(
        session,
        WorkItemPartChangedV3(
            work_item_id=row.work_item_id, part="reminder", part_id=row.id, change=change
        ),
        aggregate_id=row.work_item_id,
    )


async def _sees(session: AsyncSession, subject: Subject, record: WorkItem) -> bool:
    wtype = TYPES[WorkItemTypeCode(record.type)]
    try:
        await items.visible_record(session, subject, wtype, record.id)
    except (NotFound, PermissionDenied):
        return False
    return True


async def on_record(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> list[WorkItemReminder]:
    """The subject's own reminders on a record they can see, open first (AC2)."""
    await items.visible_record(session, subject, wtype, record_id)
    rows = await session.scalars(
        select(WorkItemReminder)
        .where(
            WorkItemReminder.work_item_id == record_id,
            WorkItemReminder.user_id == subject.user_id,
            WorkItemReminder.deleted_at.is_(None),
        )
        .order_by(WorkItemReminder.done_at.is_not(None), WorkItemReminder.remind_at)
    )
    return list(rows)


async def mine(session: AsyncSession, subject: Subject, *, open_only: bool) -> list[ReminderView]:
    """The subject's reminders on every record; one they can no longer see says so."""
    query = (
        select(WorkItemReminder, WorkItem)
        .join(WorkItem, WorkItem.id == WorkItemReminder.work_item_id)
        .where(WorkItemReminder.user_id == subject.user_id, WorkItemReminder.deleted_at.is_(None))
        .order_by(WorkItemReminder.remind_at)
        .limit(MAX_OPEN)
    )
    if open_only:
        query = query.where(WorkItemReminder.done_at.is_(None))
    found: list[ReminderView] = []
    for row, record in (await session.execute(query)).all():
        seen = record.deleted_at is None and await _sees(session, subject, record)
        found.append(
            ReminderView(
                row,
                record.type,
                record.display_id if seen else None,
                record.subject if seen else None,
            )
        )
    return found


async def create(  # noqa: PLR0913 - the record, the reminder and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    values: dict[str, Any],
    *,
    source: Source,
) -> WorkItemReminder:
    """A reminder of the subject's own on a record they can see."""
    del source  # personal: never in the record's history
    record = await items.visible_record(session, subject, wtype, record_id)
    open_count = await session.scalar(
        select(func.count())
        .select_from(WorkItemReminder)
        .where(
            WorkItemReminder.user_id == subject.user_id,
            WorkItemReminder.deleted_at.is_(None),
            WorkItemReminder.done_at.is_(None),
        )
    )
    if (open_count or 0) >= MAX_OPEN:
        raise _problems([("note", "too_many_items")])
    row = await ReminderRepository(session).add(
        WorkItemReminder(
            work_item_id=record.id,
            user_id=subject.user_id,
            **{"alert_minutes": 0, **_clean(values, creating=True)},
        )
    )
    await _signal(session, row, "added")
    return row


async def _own(session: AsyncSession, subject: Subject, reminder_id: uuid.UUID) -> WorkItemReminder:
    found: WorkItemReminder | None = await session.scalar(
        select(WorkItemReminder).where(
            WorkItemReminder.id == reminder_id,
            WorkItemReminder.user_id == subject.user_id,  # nobody else's, admins included
            WorkItemReminder.deleted_at.is_(None),
        )
    )
    if found is None:
        raise NotFound(code="reminder_not_found")
    return found


async def update(
    session: AsyncSession,
    subject: Subject,
    reminder_id: uuid.UUID,
    values: dict[str, Any],
    *,
    expected_version: int,
) -> WorkItemReminder:
    """Change, complete (`done` true) or reopen (`done` false) one of your reminders."""
    row = await _own(session, subject, reminder_id)
    changes = _clean({k: v for k, v in values.items() if k != "done"}, creating=False)
    if "done" in values:
        changes["done_at"] = datetime.now(UTC) if values["done"] else None
    updated = await ReminderRepository(session).update(
        row.id, expected_version=expected_version, changes=changes
    )
    await _signal(session, updated, "changed")
    return updated


async def delete(
    session: AsyncSession, subject: Subject, reminder_id: uuid.UUID, *, expected_version: int
) -> None:
    """Remove one of your reminders."""
    row = await _own(session, subject, reminder_id)
    removed = await ReminderRepository(session).soft_delete(
        row.id, expected_version=expected_version
    )
    await _signal(session, removed, "removed")


# --- the sweep (AC1) -----------------------------------------------------------------------------


async def sweep(session: AsyncSession, clock: Clock) -> int:
    """Raise every alert due now in this tenant, each once; how many were raised."""
    now = clock.now()
    alert_at = WorkItemReminder.remind_at - func.make_interval(
        0, 0, 0, 0, 0, WorkItemReminder.alert_minutes
    )
    rows = await session.execute(
        select(WorkItemReminder)
        .join(WorkItem, WorkItem.id == WorkItemReminder.work_item_id)
        .where(
            WorkItemReminder.deleted_at.is_(None),
            WorkItemReminder.done_at.is_(None),
            WorkItemReminder.alerted_at.is_(None),
            alert_at <= now,
            WorkItemReminder.remind_at >= now - LOOK_BACK,
            WorkItem.deleted_at.is_(None),
        )
        .with_for_update(of=WorkItemReminder, skip_locked=True)
    )
    raised = 0
    for (row,) in rows.all():
        row.alerted_at = now  # claimed: a second sweep finds it alerted
        await record_event(
            session,
            WorkItemReminderDue(
                work_item_id=row.work_item_id,
                reminder_id=row.id,
                user_id=row.user_id,
                remind_at=row.remind_at,
            ),
            aggregate_id=row.work_item_id,
        )
        raised += 1
    return raised


async def reminders_schedule(database: Database, settings: Settings) -> None:
    """Every five minutes, every tenant: the personal reminders due now."""
    del settings
    clock = SystemClock()
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        try:
            async with database.tenant_session(TenantContext(tenant)) as session:
                if raised := await sweep(session, clock):
                    log.info("personal_reminders_raised", tenant_id=str(tenant), count=raised)
        except Exception:
            log.warning("personal_reminders_failed", tenant_id=str(tenant), exc_info=True)


__all__ = [
    "ReminderView",
    "create",
    "delete",
    "mine",
    "on_record",
    "reminders_schedule",
    "sweep",
    "update",
]
