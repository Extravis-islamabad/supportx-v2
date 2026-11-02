"""One record's SLA as the record page shows it (REQ-SLA-038; wp-025-plan.md §3.6).

The record's own module checks that the reader may see the record, then asks here. Only the
latest round of each target is shown; earlier rounds (a restart after reopen) keep their stamps
in the reports.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sla.infra.models import SlaApplication, SlaCalendar, SlaPolicy, SlaTarget


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
