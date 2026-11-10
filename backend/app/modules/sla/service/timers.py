"""Firing what falls due: warnings, breaches and escalation levels (WP-025 session 3).

wp-025-plan.md §3.5, ADR-037: PostgreSQL is the truth, Temporal only the alarm clock. Whoever
wakes (the record's Temporal workflow, or the safety net for anything late) calls `fire` in one
tenant transaction. It locks the record's target clocks, re-reads them and does only what is
still due, so a second wake for the same moment finds nothing left: a warning is stamped once
(`warned_at`), a breach once (state), and a level once (its run moves from waiting to ran under
the lock, and the run is unique per clock and level). Then `next_wake` says when to come back.

The owning module hears every firing through its record type's hooks (`registry`): it stamps
the record's SLA columns with history from source "sla" and a change event (every open screen
turns live, REQ-SLA-019 AC1), and runs a level's actions.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select, text, union_all, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules.sla.domain.escalation import Level, RunState, level_of
from app.modules.sla.domain.policy import TargetKind, TargetState
from app.modules.sla.events import SlaBreached, SlaEscalated, SlaWarning
from app.modules.sla.infra.models import SlaEscalationRun, SlaTarget
from app.modules.sla.service.clock import breach_if_overdue, current_clocks, stamp_of
from app.modules.sla.service.registry import Fired, RecordState, record_type
from app.shared.clock import system_clock
from app.shared.events import record_event

log = structlog.get_logger(__name__)

# The safety net fires what is this late (D-115 D5): the waker normally comes at the moment.
SAFETY_NET_GRACE = timedelta(minutes=2)
SAFETY_NET_BATCH = 500  # records per tenant per sweep; the next sweep takes the rest


@dataclass
class FireResult:
    """What one `fire` did, and when to wake next (None: nothing pending)."""

    fired: list[Fired] = field(default_factory=list)
    next_wake: datetime | None = None


async def _pending_runs(
    session: AsyncSession, target_ids: Sequence[uuid.UUID], now: datetime
) -> list[SlaEscalationRun]:
    if not target_ids:
        return []
    return list(
        await session.scalars(
            select(SlaEscalationRun)
            .where(
                SlaEscalationRun.target_id.in_(list(target_ids)),
                SlaEscalationRun.state == RunState.WAITING.value,
                SlaEscalationRun.due_at.is_not(None),
                SlaEscalationRun.due_at <= now,
            )
            .order_by(SlaEscalationRun.due_at, SlaEscalationRun.position)
        )
    )


async def _fire_clock(  # noqa: PLR0913, PLR0917 - the clock and its record, explicit
    session: AsyncSession,
    code: str,
    record_id: uuid.UUID,
    kind: TargetKind,
    entry: Any,  # noqa: ANN401 - clock._Clock, kept private to the clock service
    now: datetime,
) -> list[Fired]:
    """Stamp a clock's warning or breach if it is due, once."""
    row = entry.row
    before = (entry.clock.state, entry.warned_at)
    warning_due = row.warning_at is not None and row.warning_at <= now
    if entry.clock.state is TargetState.RUNNING and warning_due and entry.warned_at is None:
        entry.warned_at = row.warning_at
        entry.events += ("warning",)
    breach_if_overdue(entry, now)
    if (entry.clock.state, entry.warned_at) == before:
        return []
    if entry.clock.state is TargetState.BREACHED and entry.warned_at is None:
        entry.warned_at = entry.clock.breached_at  # breached first: no separate warning
    await session.execute(
        update(SlaTarget)
        .where(SlaTarget.id == row.id)
        .values(
            state=entry.clock.state.value,
            warned_at=entry.warned_at,
            breached_at=entry.clock.breached_at,
            breach_reason=entry.breach_reason,
            version=SlaTarget.version + 1,
        )
    )
    fired: list[Fired] = []
    for name in entry.events:
        event = SlaWarning if name == "warning" else SlaBreached
        await record_event(
            session,
            event(record_type=code, record_id=record_id, kind=kind.value),
            aggregate_id=record_id,
            aggregate_version=None,
        )
        fired.append(Fired(name, kind.value))
    return fired


async def fire(session: AsyncSession, record_id: uuid.UUID, *, now: datetime) -> FireResult:
    """Do what is due on one record now, exactly once; then say when to wake next."""
    code = await session.scalar(
        select(SlaTarget.record_type).where(SlaTarget.record_id == record_id).limit(1)
    )
    result = FireResult()
    rtype = record_type(code) if code is not None else None
    if code is None or rtype is None:
        return result
    state = (
        RecordState.LIVE
        if rtype.record_state is None
        else await rtype.record_state(session, record_id)
    )
    if state is RecordState.TRASHED:
        return result  # restored as it was: its clocks fire then
    if state is RecordState.GONE:
        await _stop_gone(session, record_id, now=now)
        return result
    if rtype.lock_record is not None:
        await rtype.lock_record(session, record_id)  # the record first (registry.LockHook)
    application, current = await current_clocks(session, record_id, lock=True)
    rows = {kind: entry.row for kind, entry in current.items() if entry.row is not None}
    for kind, entry in current.items():
        if entry.row is not None and entry.clock.open:
            result.fired += await _fire_clock(session, code, record_id, kind, entry, now)
    by_target = {row.id: kind for kind, row in rows.items() if current[kind].clock.open}
    for run in await _pending_runs(session, list(by_target), now):
        result.fired.append(
            await _run_level(
                session, code, record_id, kind=by_target[run.target_id], run=run, now=now
            )
        )
    if result.fired and rtype.on_fired is not None:
        # A level's actions save the record through its own path (which may move the clocks,
        # e.g. a raised priority): stamp what the clocks hold now, not what was read above.
        application, current = await current_clocks(session, record_id)
        stamp = stamp_of(application, current)
        await rtype.on_fired(session, record_id, stamp.columns(), result.fired, now=now)
    result.next_wake = await next_wake(session, record_id)
    return result


async def _stop_gone(session: AsyncSession, record_id: uuid.UUID, *, now: datetime) -> None:
    """Stop the clocks of a record that is no longer there, once (never fired again)."""
    stopped = await session.execute(
        update(SlaTarget)
        .where(
            SlaTarget.record_id == record_id,
            SlaTarget.state.in_([TargetState.RUNNING.value, TargetState.PAUSED.value]),
        )
        .values(state=TargetState.STOPPED.value, version=SlaTarget.version + 1)
        .returning(SlaTarget.id)
    )
    targets = list(stopped.scalars())
    if targets:
        await session.execute(
            update(SlaEscalationRun)
            .where(
                SlaEscalationRun.target_id.in_(targets),
                SlaEscalationRun.state == RunState.WAITING.value,
            )
            .values(state=RunState.CANCELLED.value, version=SlaEscalationRun.version + 1)
        )
        log.warning("sla_record_gone", record_id=str(record_id), stopped=len(targets), at=str(now))


async def _run_level(  # noqa: PLR0913 - the run and its record, explicit
    session: AsyncSession,
    code: str,
    record_id: uuid.UUID,
    *,
    kind: TargetKind,
    run: SlaEscalationRun,
    now: datetime,
) -> Fired:
    """Run one level once: mark it ran (under the record's lock), act, record the event."""
    level: Level = level_of(run.level)
    claimed = await session.execute(
        update(SlaEscalationRun)
        .where(SlaEscalationRun.id == run.id, SlaEscalationRun.state == RunState.WAITING.value)
        .values(state=RunState.RAN.value, ran_at=now, version=SlaEscalationRun.version + 1)
        .returning(SlaEscalationRun.id)
    )
    if claimed.scalar_one_or_none() is None:  # pragma: no cover - the lock makes this unreachable
        return Fired("escalated", kind.value, level.position, run.id, skipped=True)
    outcomes: list[dict[str, object]] = []
    rtype = record_type(code)
    if level.actions and rtype is not None and rtype.run_actions is not None:
        outcomes = await rtype.run_actions(session, record_id, level, now=now)
    await session.execute(
        update(SlaEscalationRun)
        .where(SlaEscalationRun.id == run.id)
        .values(outcome={"actions": outcomes})
    )
    await record_event(
        session,
        SlaEscalated(
            record_type=code,
            record_id=record_id,
            kind=kind.value,
            run_id=run.id,
            position=level.position,
            notify=level.notify,
        ),
        aggregate_id=record_id,
        aggregate_version=None,
    )
    return Fired("escalated", kind.value, level.position, run.id)


async def escalation_run(
    session: AsyncSession, run_id: uuid.UUID
) -> tuple[uuid.UUID, Level] | None:
    """A level's run: the record it belongs to and the level as it ran (for its recipients)."""
    found = await session.execute(
        select(SlaTarget.record_id, SlaEscalationRun.level)
        .join(SlaTarget, SlaTarget.id == SlaEscalationRun.target_id)
        .where(SlaEscalationRun.id == run_id)
    )
    row = found.first()
    return (row.record_id, level_of(row.level)) if row is not None else None


async def next_wake(session: AsyncSession, record_id: uuid.UUID) -> datetime | None:
    """The earliest pending moment of the record: a warning, a due moment or a waiting level."""
    targets = select(SlaTarget.id).where(SlaTarget.record_id == record_id)
    moments = union_all(
        select(SlaTarget.warning_at.label("at")).where(
            SlaTarget.record_id == record_id,
            SlaTarget.state == TargetState.RUNNING.value,
            SlaTarget.warned_at.is_(None),
            SlaTarget.warning_at.is_not(None),
        ),
        select(SlaTarget.due_at.label("at")).where(
            SlaTarget.record_id == record_id,
            SlaTarget.state == TargetState.RUNNING.value,
            SlaTarget.due_at.is_not(None),
        ),
        select(SlaEscalationRun.due_at.label("at")).where(
            SlaEscalationRun.target_id.in_(targets),
            SlaEscalationRun.state == RunState.WAITING.value,
            SlaEscalationRun.due_at.is_not(None),
        ),
    ).subquery()
    found: datetime | None = await session.scalar(select(func.min(moments.c.at)))
    return found


async def overdue_records(
    session: AsyncSession,
    before: datetime,
    *,
    limit: int = SAFETY_NET_BATCH,
    after: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """Records of the session's tenant with something due before `before` (the safety net).

    In record order from `after`, so a sweep pages through all of them: records that are
    skipped (in the trash) never crowd out the others behind a fixed first page.
    """
    late = union_all(
        select(SlaTarget.record_id.label("record_id")).where(
            SlaTarget.state == TargetState.RUNNING.value,
            SlaTarget.warned_at.is_(None),
            SlaTarget.warning_at <= before,
        ),
        select(SlaTarget.record_id.label("record_id")).where(
            SlaTarget.state == TargetState.RUNNING.value, SlaTarget.due_at <= before
        ),
        select(SlaTarget.record_id.label("record_id"))
        .join(SlaEscalationRun, SlaEscalationRun.target_id == SlaTarget.id)
        .where(
            SlaEscalationRun.state == RunState.WAITING.value,
            SlaEscalationRun.due_at <= before,
        ),
    ).subquery()
    query = select(late.c.record_id).distinct().order_by(late.c.record_id).limit(limit)
    if after is not None:
        query = query.where(late.c.record_id > after)
    rows = await session.scalars(query)
    return list(rows)


async def safety_net(database: Database, settings: Settings) -> None:
    """Every minute: fire anything more than two minutes late, per tenant (D-115 D5).

    Catches what a down waker or scheduler missed; the lock and the run's state make a second
    firing a no-op, so this can never double-run a level.
    """
    del settings
    now = system_clock.now()
    async with database.platform_session() as platform:
        tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
    for tenant in tenants:
        try:  # one tenant never stops the others either
            await _sweep(database, tenant, now)
        except Exception:
            log.exception("sla_safety_net_tenant_failed", tenant_id=str(tenant))


async def _sweep(database: Database, tenant: uuid.UUID, now: datetime) -> None:
    """One tenant's late records, page by page, each in its own transaction."""
    after: uuid.UUID | None = None
    while True:
        async with database.tenant_session(TenantContext(tenant)) as session:
            late = await overdue_records(session, now - SAFETY_NET_GRACE, after=after)
        if not late:
            return
        after = late[-1]
        for record_id in late:
            # One record never stops the others (lane B, 2026-11-10): each fires in its own
            # transaction, and a failure is logged and left for the next run.
            try:
                async with database.tenant_session(TenantContext(tenant)) as session:
                    result = await fire(session, record_id, now=system_clock.now())
            except Exception:
                log.exception(
                    "sla_safety_net_record_failed", tenant_id=str(tenant), record_id=str(record_id)
                )
                continue
            if result.fired:
                log.warning(
                    "sla_fired_late",
                    tenant_id=str(tenant),
                    record_id=str(record_id),
                    fired=len(result.fired),
                )
