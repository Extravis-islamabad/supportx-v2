"""One record's SLA as the record page shows it (REQ-SLA-038; wp-025-plan.md §3.6).

The record's own module checks that the reader may see the record, then asks here. Only the
latest round of each target is shown; earlier rounds (a restart after reopen) keep their stamps
in the reports.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sla.domain.calendar import Calendar
from app.modules.sla.domain.setup import SystemCalendar
from app.modules.sla.infra.models import (
    SlaApplication,
    SlaCalendar,
    SlaEscalationRun,
    SlaPolicy,
    SlaTarget,
)
from app.modules.sla.service.calendars import calendar_for_maths, system_calendar_id


@dataclass(frozen=True, slots=True)
class SlaLevelRunView:
    """One escalation level of a target clock: when, and whether it waits, ran or was cancelled."""

    position: int
    anchor: str
    offset_seconds: int
    state: str
    due_at: datetime | None  # None while waiting: held by a pause
    ran_at: datetime | None
    failed_actions: int  # actions that could not be done (REQ-SLA-024 AC3)


@dataclass(frozen=True, slots=True)
class SlaTargetView:
    """One target clock: where it stands, and a due date set by hand if there is one."""

    kind: str
    round: int
    state: str
    target_seconds: int
    used_seconds: int
    paused_seconds: int
    running_since: datetime | None
    paused_since: datetime | None
    due_at: datetime | None
    warning_at: datetime | None
    met_at: datetime | None
    met_how: str | None
    breached_at: datetime | None
    breach_seconds: int | None
    calendar_id: uuid.UUID | None
    calendar_name: str | None
    manual_due_at: datetime | None
    manual_by: uuid.UUID | None
    manual_reason: str | None
    manual_at: datetime | None
    warned_at: datetime | None = None
    levels: tuple[SlaLevelRunView, ...] = ()


@dataclass(frozen=True, slots=True)
class SlaRecordView:
    """The record's current policy (None: no SLA), why it applies, and its targets."""

    policy_id: uuid.UUID | None
    policy_name: str | None
    reason: str | None
    applied_at: datetime | None
    targets: tuple[SlaTargetView, ...]


async def record_sla(session: AsyncSession, record_id: uuid.UUID) -> SlaRecordView:
    """The SLA of one record (the caller has checked the reader may see the record)."""
    application = await session.scalar(
        select(SlaApplication).where(
            SlaApplication.record_id == record_id, SlaApplication.current.is_(True)
        )
    )
    rows = list(
        await session.scalars(
            select(SlaTarget).where(SlaTarget.record_id == record_id).order_by(SlaTarget.round)
        )
    )
    latest = {row.kind: row for row in rows}  # the last round of each kind wins
    calendar_ids = {r.calendar_id for r in latest.values() if r.calendar_id is not None}
    calendars: dict[uuid.UUID, str] = {}
    if calendar_ids:
        found = await session.execute(
            select(SlaCalendar.id, SlaCalendar.name).where(SlaCalendar.id.in_(calendar_ids))
        )
        calendars = {row.id: row.name for row in found}
    runs: dict[uuid.UUID, list[SlaLevelRunView]] = {}
    target_ids = [r.id for r in latest.values()]
    if target_ids:
        for run in await session.scalars(
            select(SlaEscalationRun)
            .where(SlaEscalationRun.target_id.in_(target_ids))
            .order_by(SlaEscalationRun.position)
        ):
            outcome = run.outcome or {}
            runs.setdefault(run.target_id, []).append(
                SlaLevelRunView(
                    position=run.position,
                    anchor=str(run.level.get("anchor", "due")),
                    offset_seconds=int(run.level.get("offset_seconds", 0)),
                    state=run.state,
                    due_at=run.due_at,
                    ran_at=run.ran_at,
                    failed_actions=sum(1 for a in outcome.get("actions", []) if not a.get("ok")),
                )
            )
    policy_name = None
    if application is not None and application.policy_id is not None:
        policy_name = await session.scalar(
            select(SlaPolicy.name).where(SlaPolicy.id == application.policy_id)
        )
    targets = tuple(
        SlaTargetView(
            kind=row.kind,
            round=row.round,
            state=row.state,
            target_seconds=row.target_seconds,
            used_seconds=row.used_seconds,
            paused_seconds=row.paused_seconds,
            running_since=row.running_since,
            paused_since=row.paused_since,
            due_at=row.due_at,
            warning_at=row.warning_at,
            met_at=row.met_at,
            met_how=row.met_how,
            breached_at=row.breached_at,
            breach_seconds=row.breach_seconds,
            calendar_id=row.calendar_id,
            calendar_name=calendars.get(row.calendar_id) if row.calendar_id else None,
            manual_due_at=row.manual_due_at,
            manual_by=row.manual_by,
            manual_reason=row.manual_reason,
            manual_at=row.manual_at,
            warned_at=row.warned_at,
            levels=tuple(runs.get(row.id, ())),
        )
        for _, row in sorted(latest.items())
    )
    has_sla = application is not None and bool(targets)
    return SlaRecordView(
        policy_id=application.policy_id if has_sla and application else None,
        policy_name=policy_name if has_sla else None,
        reason=application.reason if has_sla and application else None,
        applied_at=application.applied_at if has_sla and application else None,
        targets=targets,
    )


OPEN_STATES = ("running", "paused", "breached")


async def open_records_on_calendar(session: AsyncSession, calendar_id: uuid.UUID) -> int:
    """How many records have an open target on this calendar (REQ-SLA-010 AC3).

    A calendar change reaches them at their next recalculation; the admin sees the number
    before saving.
    """
    count = await session.scalar(
        select(func.count(func.distinct(SlaTarget.record_id))).where(
            SlaTarget.calendar_id == calendar_id, SlaTarget.state.in_(OPEN_STATES)
        )
    )
    return int(count or 0)


async def record_calendar(session: AsyncSession, record_id: uuid.UUID) -> Calendar:
    """The calendar a record's own "business days" use (auto-close, WP-020f D4 on WP-025).

    Its resolution target's calendar (latest round), else the tenant's operating hours.
    """
    calendar_id = await session.scalar(
        select(SlaTarget.calendar_id)
        .where(
            SlaTarget.record_id == record_id,
            SlaTarget.kind == "resolution",
            SlaTarget.calendar_id.is_not(None),
        )
        .order_by(SlaTarget.round.desc())
        .limit(1)
    )
    if calendar_id is None:
        calendar_id = await system_calendar_id(session, SystemCalendar.OPERATING_HOURS)
    return await calendar_for_maths(session, calendar_id)
