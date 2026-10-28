"""Tasks, worklogs and links of a work item (WP-020e; REQ-INC-067, 072, 084). Pure rules.

Worklogs keep start, end and duration consistent (REQ-INC-067 AC1/AC2): a start is required; the
end or the duration fills the other; when both are given they must agree; the end is never
before the start. Times are whole minutes, as people log them.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

TITLE_MAX = 200
COMMENT_MAX = 500
DESCRIPTION_MAX = 4000
MAX_TASKS = 200  # per record
MAX_DURATION_MINUTES = 7 * 24 * 60  # one worklog covers at most a week


class TaskStatus(StrEnum):
    """A task's own simple life cycle (REQ-INC-072)."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELED = "canceled"


# Open work for the closing checks (WP-020f port): what is neither done nor canceled.
OPEN_TASK_STATUSES = (TaskStatus.OPEN, TaskStatus.IN_PROGRESS)


class TaskPriority(StrEnum):
    """How urgent a task is, relative to the record's other tasks."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class WorklogType(StrEnum):
    """What the time was spent on (D-111: a fixed list in MVP; admin pick lists later)."""

    INVESTIGATION = "investigation"
    FIX = "fix"
    COMMUNICATION = "communication"
    TRAVEL = "travel"
    OTHER = "other"


class LinkKind(StrEnum):
    """How two records are linked (REQ-INC-084; `follows` from WP-020f's follow-up records)."""

    RELATED = "related"  # symmetrical
    FOLLOWS = "follows"  # source follows target (a reply after the reopen window)


class WorklogProblem(StrEnum):
    """Why worklog times are refused (field problem codes)."""

    START_REQUIRED = "required"
    END_OR_DURATION = "end_or_duration_required"
    END_BEFORE_START = "end_before_start"
    DURATION_MISMATCH = "duration_mismatch"
    DURATION_RANGE = "out_of_range"


@dataclass(frozen=True)
class WorklogTimes:
    """Consistent times of one worklog."""

    started_at: datetime
    ended_at: datetime
    minutes: int


def worklog_times(  # noqa: PLR0911 - one return per rule, in the order they are checked
    started_at: datetime | None, ended_at: datetime | None, minutes: int | None
) -> WorklogTimes | tuple[str, WorklogProblem]:
    """The worklog's times, or (field, problem) when they do not hold together."""
    if started_at is None:
        return "started_at", WorklogProblem.START_REQUIRED
    if ended_at is None and minutes is None:
        return "ended_at", WorklogProblem.END_OR_DURATION
    if minutes is not None and not 1 <= minutes <= MAX_DURATION_MINUTES:
        return "minutes", WorklogProblem.DURATION_RANGE
    if ended_at is not None and ended_at < started_at:
        return "ended_at", WorklogProblem.END_BEFORE_START
    if ended_at is None:
        assert minutes is not None  # noqa: S101 - checked above (one of the two is given)
        return WorklogTimes(started_at, started_at + timedelta(minutes=minutes), minutes)
    spent = round((ended_at - started_at).total_seconds() / 60)
    if minutes is not None and minutes != spent:
        return "minutes", WorklogProblem.DURATION_MISMATCH
    if not 1 <= spent <= MAX_DURATION_MINUTES:
        return "ended_at", WorklogProblem.DURATION_RANGE
    return WorklogTimes(started_at, ended_at, spent)


def moved(ids: list[str], index: int, by: int) -> list[str] | None:
    """`ids` with the item at `index` moved `by` places (None: it cannot move that way)."""
    target = index + by
    if not 0 <= index < len(ids) or not 0 <= target < len(ids):
        return None
    order = list(ids)
    order.insert(target, order.pop(index))
    return order
