"""How long a record spent in each status, with each group and technician (REQ-INC-071).

Pure: the record's timeline (its start, the status, group and technician it started with, and
every later change of those, oldest first) is cut into segments, each measured by the caller's
clock (business hours from the record's calendar, or calendar hours). Reopening only adds
segments, so earlier time is never reset (AC3).

Open time is the time in an open or paused status (paused included); group and technician time
count only while the record is open (after closing nobody is working on it). Paused time is the
time in a paused status (AC1). A closed or cancelled spell is not counted at all: it would only
grow each day the record stays closed (lane C's #432 review); reopening counts again.
"""

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.modules.work_items.domain.lifecycle import FINAL_CATEGORIES, StatusCategory

TRACKED = ("status", "group_id", "technician_id")
OPEN = frozenset({StatusCategory.OPEN, StatusCategory.PAUSED})


@dataclass(frozen=True)
class Step:
    """A change of one tracked field at a time, from `old` to `value`."""

    at: datetime
    field: str
    old: str | None
    value: str | None


@dataclass(frozen=True)
class TimeAnalysis:
    """Seconds, per bucket; None keys are "no group" or "nobody"."""

    open_seconds: int
    paused_seconds: int
    by_status: dict[str, int]
    by_group: dict[str | None, int]
    by_technician: dict[str | None, int]


def analyse(  # noqa: PLR0913 - the timeline and how to read and measure it, explicit
    start: datetime,
    end: datetime,
    initial: Mapping[str, str | None],
    steps: Sequence[Step],
    *,
    category: Callable[[str], StatusCategory],
    measure: Callable[[datetime, datetime], int],
) -> TimeAnalysis:
    """The time analysis from `start` to `end`; steps outside that span are clamped to it."""
    state = {name: initial.get(name) for name in TRACKED}
    by_status: dict[str, int] = defaultdict(int)
    by_group: dict[str | None, int] = defaultdict(int)
    by_technician: dict[str | None, int] = defaultdict(int)
    open_seconds = paused_seconds = 0
    ordered = sorted((s for s in steps if s.field in TRACKED), key=lambda s: s.at)
    cursor = start
    for at, change in [*((min(max(s.at, start), end), s) for s in ordered), (end, None)]:
        if at > cursor and state["status"] is not None:
            status = str(state["status"])
            kind = category(status)
            seconds = 0 if kind in FINAL_CATEGORIES else measure(cursor, at)
            if seconds:
                by_status[status] += seconds
            if kind in OPEN:
                open_seconds += seconds
                by_group[state["group_id"]] += seconds
                by_technician[state["technician_id"]] += seconds
            if kind is StatusCategory.PAUSED:
                paused_seconds += seconds
        cursor = max(cursor, at)
        if change is not None:
            state[change.field] = change.value
    return TimeAnalysis(
        open_seconds, paused_seconds, dict(by_status), dict(by_group), dict(by_technician)
    )


def initial_values(
    current: Mapping[str, str | None], steps: Sequence[Step]
) -> dict[str, str | None]:
    """What each tracked field started as: its first change's old value, else its value now."""
    found = {name: current.get(name) for name in TRACKED}
    seen: set[str] = set()
    for step in sorted(steps, key=lambda s: s.at):
        if step.field in TRACKED and step.field not in seen:
            seen.add(step.field)
            found[step.field] = step.old
    return found


__all__ = ["OPEN", "TRACKED", "Step", "TimeAnalysis", "analyse", "initial_values"]
