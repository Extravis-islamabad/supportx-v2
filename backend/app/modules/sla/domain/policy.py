"""SLA policies and the clock arithmetic (WP-025 session 2; wp-025-plan.md §3.4, D-115).

Pure Python, no I/O. The service loads policies, the record snapshot and calendars, and calls:

- `match(...)`: the first enabled policy, in order, whose conditions the record meets; the
  fallback (always last, no conditions) when none does (REQ-SLA-001..004);
- `never_matching(...)`: policies that can never be reached, for the warning (REQ-SLA-001 AC);
- `targets_for(...)`: the target rows that apply to a priority (a row for that priority wins
  over the "all priorities" row);
- the clock functions (`start`, `pause`, `resume`, `meet`, `stop`, `retarget`, `set_by_hand`),
  which take a `TargetClock` and return the next one plus what happened.

Times are UTC instants; durations are whole business seconds of the target's calendar. A target
measured in business days is converted with that calendar's working day (§2: "a business day is
one day of the calendar's operating hours"); around the clock a day is 24 hours.
"""

import enum
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from app.modules.sla.domain.calendar import Calendar

Condition = Callable[[Any], bool]  # the record snapshot -> matches (the in-memory DSL evaluator)


class TargetKind(enum.StrEnum):
    """What a target measures."""

    FIRST_RESPONSE = "first_response"
    RESOLUTION = "resolution"


class TargetUnit(enum.StrEnum):
    """The unit an admin set a target in."""

    MINUTES = "minutes"
    HOURS = "hours"
    BUSINESS_DAYS = "business_days"


class CalendarSource(enum.StrEnum):
    """Where a target's calendar comes from (REQ-SLA-013)."""

    SITE = "site"  # the record's site calendar (default)
    GROUP = "group"  # the assigned group's calendar (follow the sun)
    FIXED = "fixed"
    AROUND_THE_CLOCK = "around_the_clock"


class TargetState(enum.StrEnum):
    """Where a target's clock stands."""

    RUNNING = "running"
    PAUSED = "paused"
    MET = "met"
    BREACHED = "breached"  # past due and still open (session 3 stamps it at the due moment)
    STOPPED = "stopped"  # closed or canceled before it was met


class PriorityRule(enum.StrEnum):
    """What a priority change does to open targets (D-115 D2)."""

    RECALCULATE = "recalculate"  # from the SLA start, minus pauses (default)
    RESTART = "restart"  # the full new target from the change


class ReopenRule(enum.StrEnum):
    """What a reopen does to the resolution target (REQ-SLA-029)."""

    RESUME = "resume"  # time spent resolved does not count (default)
    RESTART = "restart"  # a new round with the full target


class MetHow(enum.StrEnum):
    """How a target was met (D-115 D8: "met at resolution" is its own labelled state)."""

    ON_TIME = "on_time"
    LATE = "late"
    AT_RESOLUTION = "at_resolution"  # a response target closed by the resolution notice


@dataclass(frozen=True)
class PolicyRule:
    """A policy as matching sees it."""

    id: uuid.UUID
    position: int
    enabled: bool
    fallback: bool
    has_conditions: bool
    matches: Condition


def match(policies: Sequence[PolicyRule], record: Any) -> PolicyRule | None:  # noqa: ANN401 - the snapshot
    """The first enabled policy (by position) that the record meets; else the fallback."""
    ordered = sorted(
        (p for p in policies if p.enabled and not p.fallback), key=lambda p: p.position
    )
    for policy in ordered:
        if policy.matches(record):
            return policy
    return next((p for p in policies if p.fallback), None)


def never_matching(policies: Sequence[PolicyRule]) -> list[uuid.UUID]:
    """Enabled policies below one with no conditions: nothing can ever reach them."""
    found: list[uuid.UUID] = []
    catch_all = False
    for policy in sorted((p for p in policies if not p.fallback), key=lambda p: p.position):
        if catch_all and policy.enabled:
            found.append(policy.id)
        if policy.enabled and not policy.has_conditions:
            catch_all = True
    return found


@dataclass(frozen=True)
class TargetRow:
    """One row of a policy's target table."""

    kind: TargetKind
    priority: str | None  # None: every priority without a row of its own
    amount: int | None  # None: not tracked
    unit: TargetUnit
    source: CalendarSource = CalendarSource.SITE
    fixed_calendar_id: uuid.UUID | None = None


def targets_for(rows: Sequence[TargetRow], priority: str | None) -> dict[TargetKind, TargetRow]:
    """Per kind, the row for `priority`, else the all-priorities row; untracked rows dropped."""
    chosen: dict[TargetKind, TargetRow] = {}
    for kind in TargetKind:
        own = next((r for r in rows if r.kind is kind and r.priority == priority), None)
        row = own or next((r for r in rows if r.kind is kind and r.priority is None), None)
        if row is not None and row.amount is not None:
            chosen[kind] = row
    return chosen


def target_seconds(row: TargetRow, calendar: Calendar) -> int:
    """The row's target in business seconds of its calendar."""
    amount = row.amount or 0
    if row.unit is TargetUnit.MINUTES:
        return amount * 60
    if row.unit is TargetUnit.HOURS:
        return amount * 3600
    return amount * calendar.day_seconds()


def target_problems(rows: Sequence[TargetRow]) -> list[tuple[int, str]]:
    """(row index, code) for target rows an admin cannot save."""
    problems: list[tuple[int, str]] = []
    seen: set[tuple[TargetKind, str | None]] = set()
    for index, row in enumerate(rows):
        key = (row.kind, row.priority)
        if key in seen:
            problems.append((index, "target_duplicate"))
        seen.add(key)
        if row.amount is not None and not 1 <= row.amount <= 100_000:  # noqa: PLR2004 - sane bound
            problems.append((index, "target_amount_invalid"))
        if row.source is CalendarSource.FIXED and row.fixed_calendar_id is None:
            problems.append((index, "fixed_calendar_required"))
        if row.source is not CalendarSource.FIXED and row.fixed_calendar_id is not None:
            problems.append((index, "fixed_calendar_unused"))
    return problems


# --- the clock ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetClock:
    """One target's clock (one row of `sla_targets` for one round).

    `used` is business seconds already counted; while running, the due moment is
    `calendar.add(running_since, target - used)`. A due date set by hand wins until cleared.
    """

    kind: TargetKind
    target: int  # business seconds
    used: int = 0
    state: TargetState = TargetState.RUNNING
    running_since: datetime | None = None
    due_at: datetime | None = None
    met_at: datetime | None = None
    met_how: MetHow | None = None
    breached_at: datetime | None = None
    manual_due_at: datetime | None = None
    paused_seconds: int = 0  # business seconds spent paused (REQ-SLA-016 history)
    paused_since: datetime | None = None

    @property
    def open(self) -> bool:
        """Whether the clock can still change (not met or stopped)."""
        return self.state in {TargetState.RUNNING, TargetState.PAUSED, TargetState.BREACHED}


def _due(clock: TargetClock, calendar: Calendar) -> datetime | None:
    if clock.manual_due_at is not None:
        return clock.manual_due_at
    if clock.running_since is None:
        return None
    return calendar.add(clock.running_since, max(clock.target - clock.used, 0))


def start(kind: TargetKind, target: int, now: datetime, calendar: Calendar) -> TargetClock:
    """A new clock, running from `now`."""
    clock = TargetClock(kind=kind, target=target, running_since=now)
    return replace(clock, due_at=_due(clock, calendar))


def pause(clock: TargetClock, now: datetime, calendar: Calendar) -> TargetClock:
    """Into the paused category: count the time so far; the due moment is cleared (§3.4)."""
    if (
        clock.state not in {TargetState.RUNNING, TargetState.BREACHED}
        or clock.running_since is None
    ):
        return clock
    used = clock.used + calendar.between(clock.running_since, now)
    return replace(
        clock,
        used=used,
        state=TargetState.PAUSED,
        running_since=None,
        due_at=clock.manual_due_at,
        paused_since=now,
    )


def resume(clock: TargetClock, now: datetime, calendar: Calendar) -> TargetClock:
    """Out of the paused category: run again from `now`; the paused business time is kept."""
    if clock.state is not TargetState.PAUSED:
        return clock
    paused = calendar.between(clock.paused_since, now) if clock.paused_since else 0
    running = replace(
        clock,
        state=TargetState.BREACHED if clock.breached_at else TargetState.RUNNING,
        running_since=now,
        paused_since=None,
        paused_seconds=clock.paused_seconds + paused,
    )
    return replace(running, due_at=_due(running, calendar))


def meet(
    clock: TargetClock, now: datetime, calendar: Calendar, *, how: MetHow | None = None
) -> TargetClock:
    """The target is met at `now` (first response, or resolve). Late when past its due moment."""
    if not clock.open:
        return clock
    counted = pause(clock, now, calendar) if clock.state is not TargetState.PAUSED else clock
    late = clock.due_at is not None and now > clock.due_at
    return replace(
        counted,
        state=TargetState.MET,
        met_at=now,
        met_how=how or (MetHow.LATE if late or clock.breached_at else MetHow.ON_TIME),
        due_at=clock.due_at,
        paused_since=None,
    )


def stop(clock: TargetClock, now: datetime, calendar: Calendar) -> TargetClock:
    """Closed or canceled while still open: stopped, never breached by the stop itself."""
    if not clock.open:
        return clock
    counted = pause(clock, now, calendar) if clock.state is not TargetState.PAUSED else clock
    return replace(counted, state=TargetState.STOPPED, paused_since=None)


def reopen(
    clock: TargetClock, now: datetime, calendar: Calendar, rule: ReopenRule, target: int
) -> TargetClock:
    """A met or stopped resolution target runs again: from `used` (resume) or anew (restart).

    Restart is a new round: the caller keeps the old clock (its stamps stay) and stores this one.
    """
    if rule is ReopenRule.RESTART:
        return start(clock.kind, target, now, calendar)
    running = replace(
        clock,
        state=TargetState.BREACHED if clock.breached_at else TargetState.RUNNING,
        running_since=now,
        met_at=None,
        met_how=None,
    )
    return replace(running, due_at=_due(running, calendar))


def retarget(  # noqa: PLR0913, PLR0917 - the change, explicit
    clock: TargetClock,
    target: int,
    now: datetime,
    calendar: Calendar,
    rule: PriorityRule,
    applied_at: datetime,
) -> TargetClock:
    """A new target (priority or policy changed): recalculated from the SLA start, or restarted.

    Met clocks never change. A due date set by hand is kept. A recalculated due moment already
    in the past is the caller's breach with reason `target_changed` (§3.4).
    """
    if not clock.open:
        return clock
    if rule is PriorityRule.RESTART:
        restarted = replace(clock, target=target, used=0, running_since=now)
        if clock.state is TargetState.PAUSED:
            restarted = replace(restarted, running_since=None)
        return replace(
            restarted, due_at=_due(restarted, calendar) if restarted.running_since else clock.due_at
        )
    del applied_at  # the used time already counts from the SLA start, minus pauses
    changed = replace(clock, target=target)
    return replace(
        changed, due_at=_due(changed, calendar) if changed.running_since else changed.manual_due_at
    )


def set_by_hand(clock: TargetClock, due_at: datetime | None, calendar: Calendar) -> TargetClock:
    """A due date set by hand (REQ-SLA-028); None clears it and the calendar takes over again."""
    if not clock.open:
        return clock
    changed = replace(clock, manual_due_at=due_at)
    return replace(changed, due_at=_due(changed, calendar))


def overdue(clock: TargetClock, now: datetime) -> bool:
    """Whether an open, running clock is past its due moment."""
    return clock.state in {TargetState.RUNNING, TargetState.BREACHED} and (
        clock.due_at is not None and now >= clock.due_at
    )
