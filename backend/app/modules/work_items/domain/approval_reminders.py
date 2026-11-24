"""Approval reminders and escalation for requests (WP-047a S3a; REQ-SR-034, REQ-SR-036 AC2).

Pure: no I/O. A pending approval gets its first reminder after a set number of working days, then
one a day up to a set count, each at a set time of day in the approver's time zone (Appendix A:
2 days, 3 reminders, 10:00). The working day after the last reminder, it is escalated as its
stage says. Time spent waiting on a clarification (REQ-SR-037) pushes the whole plan back.

An escalation adds approvers next to the primary (036 AC2: the primary's row stays open). The
primary and the rows escalated from it are one "family" and count as one vote under the stage's
rule: whichever member decides first settles it (`family_states`).
"""

import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Protocol
from zoneinfo import ZoneInfo

from app.modules.work_items.domain.approvals import ApprovalState

AFTER_DAYS = 2  # Appendix A: the first reminder after 2 working days...
COUNT = 3  # ...then up to 3 reminders...
AT = time(10, 0)  # ...at 10:00 in the approver's time zone
AFTER_DAYS_RANGE = (1, 30)
COUNT_RANGE = (0, 10)
# How far back a missed slot is still sent (a sweep that did not run); well inside the claims'
# 7-day least retention, so a purged claim can never send again.
LOOK_BACK = timedelta(days=2)
_SCAN_DAYS = 400  # a calendar with no working day in a year has no slots (never loops)


class EscalateTo(StrEnum):
    """Where a stage's approval goes after its last reminder (REQ-SR-034)."""

    BACKUP = "backup"
    APPROVER_MANAGER = "approver_manager"
    FULFILMENT_GROUP = "fulfilment_group"
    NONE = "none"


DEFAULT_ESCALATE_TO = EscalateTo.BACKUP


class Step(StrEnum):
    """What a slot of the plan does."""

    REMIND = "remind"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class Schedule:
    """The tenant's reminder schedule for requests."""

    after_days: int = AFTER_DAYS
    count: int = COUNT
    at: time = AT


@dataclass(frozen=True)
class Slot:
    """One step of the plan: the n-th reminder (1-based) or the escalation, and when."""

    step: Step
    number: int
    due: datetime


def schedule_problems(after_days: int, count: int) -> list[tuple[str, str]]:
    """Field problems of a schedule (the settings form's)."""
    found: list[tuple[str, str]] = []
    if not AFTER_DAYS_RANGE[0] <= after_days <= AFTER_DAYS_RANGE[1]:
        found.append(("approval_reminder_after_days", "out_of_range"))
    if not COUNT_RANGE[0] <= count <= COUNT_RANGE[1]:
        found.append(("approval_reminder_count", "out_of_range"))
    return found


def plan(  # noqa: PLR0913 - the plan's facts, explicit
    opened_at: datetime,
    schedule: Schedule,
    zone: ZoneInfo,
    working_day: Callable[[date], bool],
    *,
    paused: timedelta = timedelta(0),
    escalates: bool = True,
) -> list[Slot]:
    """Every slot of an approval opened at `opened_at`: its reminders, then its escalation.

    A slot is the schedule's time of day on a working day, counted in the approver's `zone` from
    the day it was opened (pushed back by `paused`). AC1: opened Monday morning, the first reminder
    is Wednesday at 10:00; a weekend or holiday is skipped.
    """
    start = (opened_at + paused).astimezone(zone)
    wanted = schedule.count + (1 if escalates else 0)
    slots: list[Slot] = []
    day = start.date()
    working = 0
    for _ in range(_SCAN_DAYS):
        if len(slots) == wanted:
            break
        day += timedelta(days=1)
        if not working_day(day):
            continue
        working += 1
        if working < schedule.after_days:
            continue
        due = datetime.combine(day, schedule.at, tzinfo=zone).astimezone(UTC)
        number = len(slots) + 1
        if number <= schedule.count:
            slots.append(Slot(Step.REMIND, number, due))
        else:
            slots.append(Slot(Step.ESCALATE, 1, due))
    return slots


def due_now(slots: Sequence[Slot], now: datetime) -> Slot | None:
    """The latest slot that has come, if it came within LOOK_BACK (older ones are skipped).

    A sweep that did not run for a while sends one reminder, never a burst, and a missed
    reminder older than that is dropped. A due escalation never expires: the service makes it
    once (its rows are the proof), however late the sweep comes.
    """
    come = [s for s in slots if s.due <= now]
    if not come:
        return None
    latest = come[-1]
    if latest.step is Step.ESCALATE:
        return latest
    return latest if now - latest.due <= LOOK_BACK else None


class FamilyRow(Protocol):
    """What `family_states` reads of an approval row."""

    @property
    def id(self) -> uuid.UUID:
        """The row's ID."""
        ...

    @property
    def escalated_from_id(self) -> uuid.UUID | None:
        """The primary it was escalated from, if any."""
        ...

    @property
    def state(self) -> str:
        """Its state code."""
        ...


_DECIDED = (ApprovalState.APPROVED, ApprovalState.REJECTED)


def family_of(row: FamilyRow) -> uuid.UUID:
    """The primary row's ID: the family a row belongs to."""
    return row.escalated_from_id or row.id


def family_states(rows: Iterable[FamilyRow]) -> list[ApprovalState]:
    """One state per family, for the stage's rule (036 AC2: an escalation adds no vote).

    A family with a decision has that decision; else it is pending while any member is; else
    it has its primary's state (withdrawn, not needed, skipped, replaced: not counted).
    """
    families: dict[uuid.UUID, list[FamilyRow]] = {}
    for row in rows:
        families.setdefault(family_of(row), []).append(row)
    found: list[ApprovalState] = []
    for root, members in families.items():
        states = [ApprovalState(m.state) for m in members]
        decided = [s for s in states if s in _DECIDED]
        if decided:
            found.append(decided[0])
        elif ApprovalState.PENDING in states:
            found.append(ApprovalState.PENDING)
        else:
            primary = next((m for m in members if m.id == root), members[0])
            found.append(ApprovalState(primary.state))
    return found
