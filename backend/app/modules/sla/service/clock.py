"""Applying SLAs to records and running their clocks (WP-025 session 2; wp-025-plan.md §3.4).

The owning module calls `on_change` inside every save of a record with SLAs, with a snapshot of
the record before (None on create) and after the save. In the same transaction this:

- picks the policy (the first enabled one whose conditions match, else the default) on create,
  and again when a field a condition may name changed (D-115 D7: otherwise a record keeps the
  targets it started with, even when an admin edits the policy later);
- starts, retargets, pauses, resumes, meets, stops and reopens the target clocks
  (`domain/policy.py` does the arithmetic) and keeps every pause with its business seconds;
- writes the outbox events, and returns what to stamp on the record (`SlaStamp`).

Session 3: a clock already past its due moment when it is stored is breached (at its due
moment, or now with reason `target_changed` after a recalculation), and each open clock's
escalation levels are scheduled as `sla_escalation_runs` (`_schedule`). Warnings, breaches and
levels that fall due later are fired by `timers.fire`, woken by Temporal or the safety net.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, NotFound
from app.modules import organization
from app.modules.sla.domain import policy as clocks
from app.modules.sla.domain.calendar import Calendar
from app.modules.sla.domain.escalation import Level, RunState, level_moment, level_of
from app.modules.sla.domain.policy import (
    CalendarSource,
    MetHow,
    PriorityRule,
    ReopenRule,
    TargetClock,
    TargetKind,
    TargetRow,
    TargetState,
    match,
    target_seconds,
    targets_for,
)
from app.modules.sla.domain.setup import SystemCalendar
from app.modules.sla.events import (
    SlaApplied,
    SlaBreached,
    SlaMet,
    SlaPaused,
    SlaRecalculated,
    SlaResumed,
    SlaSetByHand,
    SlaStopped,
)
from app.modules.sla.infra.models import (
    SlaApplication,
    SlaEscalationRun,
    SlaPause,
    SlaPolicy,
    SlaTarget,
)
from app.modules.sla.service.calendars import calendar_for_maths, system_calendar_id
from app.modules.sla.service.policies import (
    levels_of,
    policies_of,
    rules_of,
    settings_of,
    target_rows,
    targets_of,
)
from app.modules.sla.service.registry import (
    FIRST_RESPONDED_AT,
    GROUP,
    PRIORITY,
    SITE,
    STATUS,
    STATUS_CATEGORY,
    SlaRecordType,
    Snapshot,
    record_type,
)
from app.shared.api.filter_eval import evaluate
from app.shared.events import record_event
from app.shared.ids import new_id

# Status categories (the owning module's lifecycle; §3.4 reads only these codes).
OPEN, PAUSED, RESOLVED, CLOSED, CANCELED = "open", "paused", "resolved", "closed", "canceled"
DONE = frozenset({RESOLVED, CLOSED, CANCELED})


@dataclass(frozen=True)
class SlaStamp:
    """What the owning module stores on the record (list fields, filters and the panel)."""

    sla_policy_id: uuid.UUID | None
    first_response_due_at: datetime | None
    resolution_due_at: datetime | None
    # Each target's state as lists show it ("warning": running past the warning point) and
    # whether it was ever breached (REQ-SLA-019 AC2, REQ-SLA-020 AC4).
    first_response_sla_state: str | None = None
    resolution_sla_state: str | None = None
    first_response_breached: bool = False
    resolution_breached: bool = False

    def columns(self) -> dict[str, Any]:
        """As record columns."""
        return {
            "sla_policy_id": self.sla_policy_id,
            "first_response_due_at": self.first_response_due_at,
            "resolution_due_at": self.resolution_due_at,
            "first_response_sla_state": self.first_response_sla_state,
            "resolution_sla_state": self.resolution_sla_state,
            "first_response_breached": self.first_response_breached,
            "resolution_breached": self.resolution_breached,
        }


@dataclass
class _Clock:
    """One stored target clock and its state now (`row` None: a new round to insert)."""

    row: SlaTarget | None
    calendar_id: uuid.UUID
    clock: TargetClock
    round: int = 1
    events: tuple[str, ...] = ()
    warned_at: datetime | None = None
    breach_reason: str | None = None

    @property
    def shown_state(self) -> str:
        """The state lists show: a running clock past its warning point is "warning"."""
        state = self.clock.state
        if state is TargetState.RUNNING and self.warned_at is not None:
            return "warning"
        return state.value


def _from_row(row: SlaTarget) -> TargetClock:
    return TargetClock(
        kind=TargetKind(row.kind),
        target=row.target_seconds,
        used=row.used_seconds,
        state=TargetState(row.state),
        running_since=row.running_since,
        due_at=row.due_at,
        met_at=row.met_at,
        met_how=MetHow(row.met_how) if row.met_how else None,
        breached_at=row.breached_at,
        manual_due_at=row.manual_due_at,
        paused_seconds=row.paused_seconds,
        paused_since=row.paused_since,
    )


def _breach_seconds(clock: TargetClock) -> int | None:
    """How long past due a breached clock was met or stopped (REQ-SLA-020 AC2); else None."""
    if clock.breached_at is None or clock.due_at is None:
        return None
    end = clock.met_at if clock.state is TargetState.MET else None
    if end is None:
        return None
    return max(int((end - clock.due_at).total_seconds()), 0)


def _columns(clock: TargetClock, warning_at: datetime | None) -> dict[str, Any]:
    return {
        "breached_at": clock.breached_at,
        "breach_seconds": _breach_seconds(clock),
        "target_seconds": clock.target,
        "used_seconds": clock.used,
        "state": clock.state.value,
        "running_since": clock.running_since,
        "due_at": clock.due_at,
        "warning_at": warning_at,
        "met_at": clock.met_at,
        "met_how": clock.met_how.value if clock.met_how else None,
        "paused_seconds": clock.paused_seconds,
        "paused_since": clock.paused_since,
        "manual_due_at": clock.manual_due_at,
    }


def warning_moment(clock: TargetClock, calendar: Calendar, percent: int) -> datetime | None:
    """When a running clock reaches the warning point (None when paused, done or already past)."""
    if clock.state is not TargetState.RUNNING or clock.running_since is None:
        return None
    if clock.manual_due_at is not None:
        return None  # a date set by hand has no business-time share to measure
    left = clock.target * percent // 100 - clock.used
    return calendar.add(clock.running_since, left) if left > 0 else None


class _Run:
    """One `on_change` call: its caches and what it wrote."""

    def __init__(  # noqa: PLR0913, PLR0917 - the call's context, explicit
        self,
        session: AsyncSession,
        rtype: SlaRecordType,
        record_id: uuid.UUID,
        after: Snapshot,
        now: datetime,
        actor: uuid.UUID | None,
    ) -> None:
        self.session = session
        self.rtype = rtype
        self.record_id = record_id
        self.after = after
        self.now = now
        self.actor = actor
        self.calendars: dict[uuid.UUID, Calendar] = {}
        self.levels: list[Level] = []

    async def calendar(self, calendar_id: uuid.UUID) -> Calendar:
        if calendar_id not in self.calendars:
            self.calendars[calendar_id] = await calendar_for_maths(self.session, calendar_id)
        return self.calendars[calendar_id]

    async def calendar_id(self, row: TargetRow) -> uuid.UUID:
        """REQ-SLA-013: the row's calendar source; a site or group without one, the default."""
        if row.source is CalendarSource.AROUND_THE_CLOCK:
            return await system_calendar_id(self.session, SystemCalendar.AROUND_THE_CLOCK)
        if row.source is CalendarSource.FIXED and row.fixed_calendar_id is not None:
            return row.fixed_calendar_id
        site, group = await organization.unit_calendars(
            self.session, self.after.get(SITE), self.after.get(GROUP)
        )
        chosen = group if row.source is CalendarSource.GROUP and group else site
        return chosen or await system_calendar_id(self.session, SystemCalendar.OPERATING_HOURS)


async def current_clocks(
    session: AsyncSession, record_id: uuid.UUID, *, lock: bool = False
) -> tuple[SlaApplication | None, dict[TargetKind, _Clock]]:
    """The record's current application and the latest round of each target clock."""
    application = await session.scalar(
        select(SlaApplication).where(
            SlaApplication.record_id == record_id, SlaApplication.current.is_(True)
        )
    )
    query = select(SlaTarget).where(SlaTarget.record_id == record_id).order_by(SlaTarget.round)
    # The waker and a save can meet on one record: whoever comes second waits and re-reads.
    rows = await session.scalars(query.with_for_update() if lock else query)
    latest: dict[TargetKind, _Clock] = {}
    for row in rows:  # the last round of each kind wins
        latest[TargetKind(row.kind)] = _Clock(
            row=row,
            calendar_id=row.calendar_id or uuid.UUID(int=0),
            clock=_from_row(row),
            round=row.round,
            warned_at=row.warned_at,
            breach_reason=row.breach_reason,
        )
    return application, latest


def levels_in(application: SlaApplication | None) -> list[Level]:
    """The escalation levels the record started with (D-115 D7: its snapshot)."""
    if application is None:
        return []
    return [level_of(item) for item in application.snapshot.get("levels", [])]


def _condition_fields_changed(rtype: SlaRecordType, before: Snapshot, after: Snapshot) -> bool:
    return any(before.get(name) != after.get(name) for name in rtype.fields.fields)


async def _choose(run: _Run, code: str) -> tuple[SlaPolicy | None, list[TargetRow], list[Level]]:
    policies = await policies_of(run.session, code)

    def matcher(policy: SlaPolicy) -> Any:  # noqa: ANN401 - the domain's Condition
        if policy.conditions is None:
            return lambda _record: True
        tree = policy.conditions
        return lambda record: evaluate(tree, run.rtype.fields, record, now=run.now)

    named = run.rtype.preferred_policy(run.after) if run.rtype.preferred_policy else None
    row = next((p for p in policies if p.id == named and p.enabled), None) if named else None
    if row is None:
        chosen = match(rules_of(policies, matcher), run.after)
        if chosen is None:  # pragma: no cover - ensure_defaults always makes the fallback
            return None, [], []
        row = next(p for p in policies if p.id == chosen.id)
    rows = target_rows((await targets_of(run.session, [row.id]))[row.id])
    if run.rtype.target_dates_only and not (await settings_of(run.session, code)).full_sla:
        rows = [r for r in rows if r.kind == TargetKind.RESOLUTION]  # D-140 Q3: dates only
    return row, rows, (await levels_of(run.session, [row.id]))[row.id]


def _rows_snapshot(rows: list[TargetRow]) -> list[dict[str, Any]]:
    return [
        {
            "kind": r.kind.value,
            "priority": r.priority,
            "amount": r.amount,
            "unit": r.unit.value,
            "source": r.source.value,
            "fixed_calendar_id": str(r.fixed_calendar_id) if r.fixed_calendar_id else None,
        }
        for r in rows
    ]


def _rows_of(snapshot: Mapping[str, Any]) -> list[TargetRow]:
    return [
        TargetRow(
            kind=TargetKind(r["kind"]),
            priority=r["priority"],
            amount=r["amount"],
            unit=clocks.TargetUnit(r["unit"]),
            source=CalendarSource(r["source"]),
            fixed_calendar_id=uuid.UUID(r["fixed_calendar_id"]) if r["fixed_calendar_id"] else None,
        )
        for r in snapshot.get("targets", [])
    ]


async def _apply(  # noqa: PLR0913, PLR0917 - one policy decision, every kind in turn
    run: _Run,
    code: str,
    application: SlaApplication | None,
    current: dict[TargetKind, _Clock],
    rule: PriorityRule,
    reason: str,
) -> tuple[SlaApplication, list[str]]:
    """Choose the policy; start or retarget each kind; stop kinds the new targets drop."""
    policy, rows, levels = await _choose(run, code)
    priority = run.after.get(PRIORITY)
    if application is not None and policy is not None:
        same = application.policy_id == policy.id and application.snapshot.get("priority") == (
            priority
        )
        if same:
            return application, []
    changed: list[str] = []
    chosen = targets_for(rows, priority)
    for kind in TargetKind:
        row = chosen.get(kind)
        existing = current.get(kind)
        if row is None:
            if existing is not None and existing.clock.open:
                calendar = await run.calendar(existing.calendar_id)
                existing.clock = clocks.stop(existing.clock, run.now, calendar)
                existing.events += ("stopped",)
            continue
        calendar_id = await run.calendar_id(row)
        calendar = await run.calendar(calendar_id)
        seconds = target_seconds(row, calendar)
        if existing is None:
            if kind is TargetKind.FIRST_RESPONSE and run.after.get(FIRST_RESPONDED_AT):
                continue  # already answered before any SLA applied: nothing to measure
            current[kind] = _Clock(
                row=None,
                calendar_id=calendar_id,
                clock=clocks.start(kind, seconds, run.now, calendar),
            )
            changed.append(kind.value)
        elif existing.clock.open:
            existing.calendar_id = calendar_id
            existing.clock = clocks.retarget(
                existing.clock,
                seconds,
                run.now,
                calendar,
                rule,
                application.applied_at if application else run.now,
            )
            existing.events += ("recalculated",)
            changed.append(kind.value)
    if application is not None:
        application.current = False
    await run.session.flush()
    fresh = SlaApplication(
        id=new_id(),
        tenant_id=run.session.info[SESSION_TENANT_KEY].tenant_id,
        record_type=code,
        record_id=run.record_id,
        policy_id=policy.id if policy else None,
        policy_version=policy.version if policy else None,
        reason=reason,
        snapshot={
            "priority": priority,
            "targets": _rows_snapshot(rows),
            "levels": [level.as_json() for level in levels],
        },
        applied_at=run.now,
        current=True,
        created_by=run.actor,
        updated_by=run.actor,
    )
    run.session.add(fresh)
    return fresh, changed


async def _status(  # noqa: PLR0913 - the move and the policy's rules, explicit
    run: _Run,
    current: dict[TargetKind, _Clock],
    pausing: list[str],
    reopen_rule: ReopenRule,
    *,
    old: str | None,
    new: str,
) -> None:
    """§3.4: what a move between status categories does to each clock."""
    for kind, found in list(current.items()):
        entry = found
        calendar = await run.calendar(entry.calendar_id)
        clock = entry.clock
        if new in DONE and old not in DONE:
            if new == RESOLVED:
                how = MetHow.AT_RESOLUTION if kind is TargetKind.FIRST_RESPONSE else None
                met = clocks.meet(clock, run.now, calendar, how=how)
                entry.events += ("met",) if met is not clock else ()
                clock = met
            stopped = clocks.stop(clock, run.now, calendar)
            entry.events += ("stopped",) if stopped is not clock else ()
            clock = stopped
        elif old in DONE and new not in DONE and kind is TargetKind.RESOLUTION:
            if reopen_rule is ReopenRule.RESTART:
                current[kind] = _Clock(
                    row=None,
                    calendar_id=entry.calendar_id,
                    clock=clocks.start(kind, clock.target, run.now, calendar),
                    round=entry.round + 1,
                    events=("recalculated",),
                )
                entry = current[kind]
                clock = entry.clock
            else:
                clock = clocks.reopen(clock, run.now, calendar, reopen_rule, clock.target)
                entry.events += ("recalculated",)
        if kind.value in pausing:
            if new == PAUSED and clock.state is not TargetState.PAUSED and clock.open:
                clock = clocks.pause(clock, run.now, calendar)
                entry.events += ("paused",)
            elif new != PAUSED and clock.state is TargetState.PAUSED and new not in DONE:
                clock = clocks.resume(clock, run.now, calendar)
                entry.events += ("resumed",)
        entry.clock = clock


async def _store(run: _Run, code: str, current: dict[TargetKind, _Clock], percent: int) -> None:
    """Write each changed clock, open and close its pauses, and record the events."""
    tenant = run.session.info[SESSION_TENANT_KEY].tenant_id
    status = run.after.get(STATUS)
    for kind, entry in current.items():
        if not entry.events and entry.row is not None:
            continue
        calendar = await run.calendar(entry.calendar_id)
        breach_if_overdue(entry, run.now)
        warning_at = warning_moment(entry.clock, calendar, percent)
        if warning_at is None or warning_at > run.now:
            entry.warned_at = None  # the warning point moved ahead (or went): it can come again
        values = _columns(entry.clock, warning_at) | {
            "warned_at": entry.warned_at,
            "breach_reason": entry.breach_reason,
        }
        if entry.row is None:
            row = SlaTarget(
                id=new_id(),
                tenant_id=tenant,
                record_type=code,
                record_id=run.record_id,
                kind=kind.value,
                round=entry.round,
                calendar_id=entry.calendar_id,
                created_by=run.actor,
                updated_by=run.actor,
                **values,
            )
            run.session.add(row)
            await run.session.flush()
            entry.row = row
        else:
            await run.session.execute(
                update(SlaTarget)
                .where(SlaTarget.id == entry.row.id)
                .values(
                    **values,
                    calendar_id=entry.calendar_id,
                    version=SlaTarget.version + 1,
                    updated_by=run.actor,
                )
            )
        target_id = entry.row.id
        if "paused" in entry.events:
            run.session.add(
                SlaPause(
                    id=new_id(),
                    tenant_id=tenant,
                    target_id=target_id,
                    started_at=run.now,
                    cause=str(status) if status else None,
                    person_id=run.actor,
                )
            )
        if "resumed" in entry.events or ("stopped" in entry.events or "met" in entry.events):
            await _close_pause(run, target_id, calendar)
        await schedule_levels(
            run.session, entry, calendar, [lv for lv in run.levels if lv.kind is kind], percent
        )
    await run.session.flush()
    for kind, entry in current.items():
        for name in dict.fromkeys(entry.events):
            await record_event(
                run.session,
                _EVENTS[name](record_type=code, record_id=run.record_id, kind=kind.value),
                aggregate_id=run.record_id,
                aggregate_version=None,
            )


def breach_if_overdue(entry: _Clock, now: datetime) -> None:
    """A running clock already past due when stored is breached (REQ-SLA-020, §3.4).

    After a recalculation the new due moment may lie in the past: breached now, with reason
    `target_changed`. Otherwise the due moment simply passed before the waker came: breached at
    the due moment, `time_passed` (`timers.fire` does the same).
    """
    clock = entry.clock
    if clock.state is not TargetState.RUNNING or not clocks.overdue(clock, now):
        return
    if clock.due_at is None:  # pragma: no cover - overdue() needs a due moment
        return
    changed = "recalculated" in entry.events
    entry.clock = clocks.breach(clock, now if changed else clock.due_at)
    entry.breach_reason = "target_changed" if changed else "time_passed"
    entry.events += ("breached",)


async def schedule_levels(
    session: AsyncSession,
    entry: _Clock,
    calendar: Calendar,
    levels: list[Level],
    percent: int,
) -> None:
    """Keep the clock's escalation runs in step with it (REQ-SLA-025).

    Waiting runs move with the clock: held (no moment) while paused, cancelled once it is met or
    stopped, or when the record's levels no longer include them. A run that ran stays as it is.
    """
    if entry.row is None:  # pragma: no cover - stored before scheduling
        return
    tenant = session.info[SESSION_TENANT_KEY].tenant_id
    runs = {
        r.level_key: r
        for r in await session.scalars(
            select(SlaEscalationRun).where(SlaEscalationRun.target_id == entry.row.id)
        )
    }
    wanted = {level.key: level for level in levels}
    done = not entry.clock.open
    for key, run in runs.items():
        if run.state == RunState.WAITING and (done or key not in wanted):
            run.state = RunState.CANCELLED.value
            run.due_at = None
            run.version += 1
    if done:
        return
    for key, level in wanted.items():
        moment = level_moment(level, entry.clock, calendar, percent)
        existing = runs.get(key)
        if existing is None:
            session.add(
                SlaEscalationRun(
                    id=new_id(),
                    tenant_id=tenant,
                    target_id=entry.row.id,
                    level_key=key,
                    position=level.position,
                    level=level.as_json(),
                    due_at=moment,
                    state=RunState.WAITING.value,
                )
            )
        elif existing.state == RunState.WAITING and existing.due_at != moment:
            existing.due_at = moment
            existing.version += 1


async def _close_pause(run: _Run, target_id: uuid.UUID, calendar: Calendar) -> None:
    open_pause = await run.session.scalar(
        select(SlaPause).where(SlaPause.target_id == target_id, SlaPause.ended_at.is_(None))
    )
    if open_pause is None:
        return
    open_pause.ended_at = run.now
    open_pause.business_seconds = calendar.between(open_pause.started_at, run.now)
    open_pause.calendar_seconds = int((run.now - open_pause.started_at).total_seconds())


_EVENTS: dict[str, Any] = {
    "paused": SlaPaused,
    "resumed": SlaResumed,
    "met": SlaMet,
    "stopped": SlaStopped,
    "recalculated": SlaRecalculated,
    "set_by_hand": SlaSetByHand,
    "breached": SlaBreached,
}


def stamp_of(application: SlaApplication | None, current: dict[TargetKind, _Clock]) -> SlaStamp:
    """What the owning module stores on the record, from its clocks now."""

    def due(kind: TargetKind) -> datetime | None:
        entry = current.get(kind)
        return entry.clock.due_at if entry else None

    def state(kind: TargetKind) -> str | None:
        entry = current.get(kind)
        return entry.shown_state if entry else None

    def breached(kind: TargetKind) -> bool:
        entry = current.get(kind)
        return entry is not None and entry.clock.breached_at is not None

    return SlaStamp(
        # A policy without a target for the record's priority is no SLA (REQ-INC-011 AC2).
        sla_policy_id=application.policy_id if application and current else None,
        first_response_due_at=due(TargetKind.FIRST_RESPONSE),
        resolution_due_at=due(TargetKind.RESOLUTION),
        first_response_sla_state=state(TargetKind.FIRST_RESPONSE),
        resolution_sla_state=state(TargetKind.RESOLUTION),
        first_response_breached=breached(TargetKind.FIRST_RESPONSE),
        resolution_breached=breached(TargetKind.RESOLUTION),
    )


def _reason(
    rtype: SlaRecordType,
    application: SlaApplication | None,
    before: Snapshot | None,
    after: Snapshot,
) -> str | None:
    """Why the policy is chosen (again) in this save, or None when it stays."""
    if application is None:
        return "created"
    if before is None or not _condition_fields_changed(rtype, before, after):
        return None
    return (
        "priority_changed" if before.get(PRIORITY) != after.get(PRIORITY) else "condition_changed"
    )


async def on_change(  # noqa: PLR0913 - the save, explicit
    session: AsyncSession,
    code: str,
    record_id: uuid.UUID,
    before: Snapshot | None,
    after: Snapshot,
    *,
    now: datetime,
    actor: uuid.UUID | None = None,
) -> SlaStamp:
    """Apply and run the record's SLA for one save; returns the columns to stamp on it."""
    rtype = record_type(code)
    if rtype is None:
        raise NotFound(code="sla_record_type_not_found", params={"record_type": code})
    actor = actor or session.info[SESSION_TENANT_KEY].user_id
    run = _Run(session, rtype, record_id, after, now, actor)
    settings = await settings_of(session, code)
    application, current = await current_clocks(session, record_id, lock=True)
    old_category = before.get(STATUS_CATEGORY) if before is not None else None
    new_category = str(after.get(STATUS_CATEGORY) or OPEN)
    live = new_category not in DONE
    applied: SlaApplication | None = application
    reason = _reason(rtype, application, before, after) if live else None
    moved_unit = before is not None and (
        before.get(SITE) != after.get(SITE) or before.get(GROUP) != after.get(GROUP)
    )
    if reason is None and application is not None and moved_unit and live:
        await _recalendar(run, application, current)
    if reason is not None:
        applied, changed = await _apply(
            run, code, application, current, PriorityRule(settings.priority_rule), reason
        )
        if applied is not application:
            await record_event(
                session,
                SlaApplied(
                    record_type=code,
                    record_id=record_id,
                    policy_id=applied.policy_id,
                    reason=reason,
                    kinds=changed,
                ),
                aggregate_id=record_id,
                aggregate_version=None,
            )
    run.levels = levels_in(applied)
    pausing = await _pausing(session, applied)
    if old_category != new_category:
        await _status(
            run,
            current,
            pausing,
            ReopenRule(settings.reopen_rule),
            old=old_category,
            new=new_category,
        )
    if before is not None and not before.get(FIRST_RESPONDED_AT) and after.get(FIRST_RESPONDED_AT):
        entry = current.get(TargetKind.FIRST_RESPONSE)
        if entry is not None and entry.clock.open:
            calendar = await run.calendar(entry.calendar_id)
            entry.clock = clocks.meet(entry.clock, now, calendar)
            entry.events += ("met",)
    await _store(run, code, current, settings.warning_percent)
    return stamp_of(applied, current)


async def set_due_by_hand(  # noqa: PLR0913 - the change and who makes it, explicit
    session: AsyncSession,
    code: str,
    record_id: uuid.UUID,
    kind: str,
    due_at: datetime | None,
    *,
    reason: str,
    now: datetime,
    actor: uuid.UUID | None = None,
) -> SlaStamp:
    """A due date set by hand, or cleared with `due_at` None (REQ-SLA-028, D-115 D11).

    The caller checks the permission. A date set by hand stays through priority and policy
    changes until cleared; clearing recalculates from the targets the record already has.
    """
    rtype = record_type(code)
    if rtype is None:
        raise NotFound(code="sla_record_type_not_found", params={"record_type": code})
    actor = actor or session.info[SESSION_TENANT_KEY].user_id
    application, current = await current_clocks(session, record_id, lock=True)
    entry = current.get(TargetKind(kind)) if kind in {k.value for k in TargetKind} else None
    if entry is None or entry.row is None:
        raise NotFound(code="sla_target_not_found", params={"kind": kind})
    if not entry.clock.open:
        raise Conflict(code="sla_target_done", params={"kind": kind})
    run = _Run(session, rtype, record_id, {}, now, actor)
    run.levels = levels_in(application)
    calendar = await run.calendar(entry.calendar_id)
    entry.clock = clocks.set_by_hand(entry.clock, due_at, calendar)
    entry.events += ("set_by_hand",)
    settings = await settings_of(session, code)
    await _store(run, code, {TargetKind(kind): entry}, settings.warning_percent)
    by_hand = due_at is not None
    await session.execute(
        update(SlaTarget)
        .where(SlaTarget.id == entry.row.id)
        .values(
            manual_by=actor if by_hand else None,
            manual_reason=reason if by_hand else None,
            manual_at=now if by_hand else None,
        )
    )
    return stamp_of(application, current)


async def _pausing(session: AsyncSession, application: SlaApplication | None) -> list[str]:
    if application is None or application.policy_id is None:
        return [k.value for k in TargetKind]
    found = await session.scalar(
        select(SlaPolicy.pausing).where(SlaPolicy.id == application.policy_id)
    )
    return list(found) if found is not None else [k.value for k in TargetKind]


async def _recalendar(
    run: _Run, application: SlaApplication, current: dict[TargetKind, _Clock]
) -> None:
    """A new site or group: open clocks whose calendar came from it move to the new calendar.

    The business time already counted stays; what is left runs on the new calendar.
    """
    rows = _rows_of(application.snapshot)
    chosen = targets_for(rows, application.snapshot.get("priority"))
    for kind, entry in current.items():
        row = chosen.get(kind)
        if row is None or not entry.clock.open:
            continue
        if row.source not in {CalendarSource.SITE, CalendarSource.GROUP}:
            continue
        calendar_id = await run.calendar_id(row)
        if calendar_id == entry.calendar_id:
            continue
        old = await run.calendar(entry.calendar_id)
        new = await run.calendar(calendar_id)
        clock = entry.clock
        if clock.state is not TargetState.PAUSED and clock.running_since is not None:
            used = clock.used + old.between(clock.running_since, run.now)
            clock = replace(clock, used=used, running_since=run.now)
            clock = clocks.set_by_hand(clock, clock.manual_due_at, new)
        entry.calendar_id = calendar_id
        entry.clock = clock
        entry.events += ("recalculated",)
