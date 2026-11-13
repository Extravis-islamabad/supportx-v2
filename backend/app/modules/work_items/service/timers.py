"""Personal timers on a record (WP-046a S3, REQ-INC-069).

A timer is its owner's own: one running per person per record, kept on the server
(`work_item_timers`) so it survives a reload and shows on every screen of theirs. Only its owner
hears of it, on their personal channel (`work_items.part.changed` v3, part `timer`). Stopping
gives the times a new worklog is prefilled with; nothing is logged until the person saves it.

When the record is resolved, closed or canceled with timers running, each is saved as a draft
worklog of its owner (AC2) and ends: a draft counts nowhere until its owner confirms it.

Auto-start (`timer_auto_start`, off by default, the coordinator): opening a record you are the
technician of starts your timer once per record, never again after you stop it.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict
from app.modules.identity_access import Subject
from app.modules.work_items.domain.lifecycle import DONE_CATEGORIES, StatusCategory
from app.modules.work_items.domain.parts import COMMENT_MAX
from app.modules.work_items.domain.types import TYPES, WorkItemType, WorkItemTypeCode
from app.modules.work_items.events import WorkItemPartChangedV3
from app.modules.work_items.infra.models import WorkItem, WorkItemTimer, WorkItemWorklog
from app.modules.work_items.service import catalogue
from app.modules.work_items.service import work_items as items
from app.shared.db.repository import Repository
from app.shared.events import record_event

TIMER_RUNNING = "timer_running"  # you already have one running on this record
NO_TIMER = "timer_not_running"
RECORD_DONE = "timer_record_done"  # resolved, closed or canceled: log time instead
DRAFT_TYPE = "other"  # a draft's worklog type; its owner changes it when confirming


class TimerRepository(Repository[WorkItemTimer]):
    """Timers of the session's tenant."""

    model = WorkItemTimer


@dataclass(frozen=True)
class Stopped:
    """What a stopped timer prefills a new worklog with (nothing is logged yet)."""

    started_at: datetime
    ended_at: datetime
    minutes: int
    comment: str | None


def _minutes(started_at: datetime, ended_at: datetime) -> int:
    return max(int((ended_at - started_at).total_seconds() // 60), 0)


async def _signal(
    session: AsyncSession, row: WorkItemTimer, change: Literal["added", "changed", "removed"]
) -> None:
    """Its owner's screens refresh; realtime tells their personal channel only."""
    await record_event(
        session,
        WorkItemPartChangedV3(
            work_item_id=row.work_item_id,
            part="timer",
            part_id=row.id,
            change=change,
        ),
        aggregate_id=row.work_item_id,
    )


async def _running(
    session: AsyncSession, record_id: uuid.UUID, user_id: uuid.UUID
) -> WorkItemTimer | None:
    found: WorkItemTimer | None = await session.scalar(
        select(WorkItemTimer).where(
            WorkItemTimer.work_item_id == record_id,
            WorkItemTimer.user_id == user_id,
            WorkItemTimer.deleted_at.is_(None),
        )
    )
    return found


def _done(record: WorkItem) -> bool:
    return StatusCategory(record.status_category) in DONE_CATEGORIES


async def mine_on(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> WorkItemTimer | None:
    """The subject's running timer on a record they may see, or None."""
    await items.visible_record(session, subject, wtype, record_id)
    return await _running(session, record_id, subject.user_id)


async def start(  # noqa: PLR0913 - the record, the comment and how, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    *,
    comment: str | None = None,
    auto: bool = False,
) -> WorkItemTimer:
    """Start your timer on a record you may log time on (as worklogs: edit, or investigator)."""
    from app.modules.work_items.service import parts  # noqa: PLC0415 - parts builds on items

    record, _full = await parts.work_access(session, subject, wtype, record_id)
    if _done(record):
        raise Conflict(code=RECORD_DONE, params={"status": record.status})
    if await _running(session, record.id, subject.user_id) is not None:
        raise Conflict(code=TIMER_RUNNING)
    text = " ".join((comment or "").split())[:COMMENT_MAX] or None
    row = await TimerRepository(session).add(
        WorkItemTimer(
            work_item_id=record.id,
            user_id=subject.user_id,
            started_at=datetime.now(UTC),
            comment=text,
            auto_started=auto,
        )
    )
    await _signal(session, row, "added")
    return row


async def stop(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> Stopped:
    """End your timer and return the worklog it prefills (AC1: 25 minutes give 25)."""
    await items.visible_record(session, subject, wtype, record_id)
    row = await _running(session, record_id, subject.user_id)
    if row is None:
        raise Conflict(code=NO_TIMER)
    ended = await TimerRepository(session).soft_delete(row.id, expected_version=row.version)
    stopped = datetime.now(UTC)
    await _signal(session, ended, "removed")
    return Stopped(row.started_at, stopped, _minutes(row.started_at, stopped), row.comment)


async def discard(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> None:
    """End your timer without logging anything."""
    await items.visible_record(session, subject, wtype, record_id)
    row = await _running(session, record_id, subject.user_id)
    if row is None:
        raise Conflict(code=NO_TIMER)
    ended = await TimerRepository(session).soft_delete(row.id, expected_version=row.version)
    await _signal(session, ended, "removed")


async def auto_start(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> WorkItemTimer | None:
    """Opening a record you are the technician of starts your timer, once (the setting).

    Off by default. Never again after it ran once on this record, even stopped; never on a
    resolved, closed or canceled one.
    """
    if not (await catalogue.load(session, wtype)).closure.timer_auto_start:
        return None
    record = await items.visible_record(session, subject, wtype, record_id)
    if record.technician_id != subject.user_id or _done(record):
        return None
    ever = await session.scalar(
        select(WorkItemTimer.id).where(
            WorkItemTimer.work_item_id == record.id, WorkItemTimer.user_id == subject.user_id
        )
    )
    if ever is not None:
        return None
    return await start(session, subject, wtype, record.id, auto=True)


async def mine(session: AsyncSession, subject: Subject) -> list[tuple[WorkItemTimer, WorkItem]]:
    """Your running timers on every record you may still see, the oldest first."""
    rows = await session.execute(
        select(WorkItemTimer, WorkItem)
        .join(WorkItem, WorkItem.id == WorkItemTimer.work_item_id)
        .where(WorkItemTimer.user_id == subject.user_id, WorkItemTimer.deleted_at.is_(None))
        .order_by(WorkItemTimer.started_at)
    )
    found: list[tuple[WorkItemTimer, WorkItem]] = []
    for timer, record in rows.tuples():
        wtype = TYPES[WorkItemTypeCode(record.type)]
        if await items.may_view(session, subject, wtype, record.id):
            found.append((timer, record))
    return found


async def save_drafts(session: AsyncSession, record: WorkItem) -> int:
    """Each running timer on a record just resolved, closed or canceled becomes a draft.

    A draft worklog of its owner (AC2), with its cost taken as a logged one's; the timer ends.
    Returns how many.
    """
    from app.modules.work_items.service import parts  # noqa: PLC0415 - parts builds on items

    running = list(
        await session.scalars(
            select(WorkItemTimer).where(
                WorkItemTimer.work_item_id == record.id, WorkItemTimer.deleted_at.is_(None)
            )
        )
    )
    now = datetime.now(UTC)
    for row in running:
        minutes = _minutes(row.started_at, now)
        rate, cost = await parts.cost_snapshot(session, row.user_id, row.started_at, minutes)
        await parts.WorklogRepository(session).add(
            WorkItemWorklog(
                work_item_id=record.id,
                owner_id=row.user_id,
                worklog_type=DRAFT_TYPE,
                started_at=row.started_at,
                ended_at=now,
                minutes=minutes,
                description=row.comment,
                draft=True,
                cost_rate=rate,
                technician_cost=cost,
                stage=record.stage,
            )
        )
        ended = await TimerRepository(session).soft_delete(row.id, expected_version=row.version)
        await _signal(session, ended, "removed")
    return len(running)


__all__ = [
    "NO_TIMER",
    "RECORD_DONE",
    "TIMER_RUNNING",
    "Stopped",
    "auto_start",
    "discard",
    "mine",
    "mine_on",
    "save_drafts",
    "start",
    "stop",
]
