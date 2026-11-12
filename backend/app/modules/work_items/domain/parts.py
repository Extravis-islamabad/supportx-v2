"""Tasks, worklogs and links of a work item (WP-020e; REQ-INC-067, 072, 084). Pure rules.

Worklogs keep start, end and duration consistent (REQ-INC-067 AC1/AC2): a start is required; the
end or the duration fills the other; when both are given they must agree; the end is never
before the start. Times are whole minutes, as people log them.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

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
    """What the time was spent on (D-112: a fixed list in MVP; admin pick lists later)."""

    INVESTIGATION = "investigation"
    FIX = "fix"
    COMMUNICATION = "communication"
    TRAVEL = "travel"
    OTHER = "other"


class LinkKind(StrEnum):
    """How two records are linked (REQ-INC-084; `follows` from WP-020f's follow-up records)."""

    RELATED = "related"  # symmetrical
    FOLLOWS = "follows"  # source follows target (a reply after the reopen window)
    CAUSED_BY = "caused_by"  # source (an incident) is caused by target (a problem), WP-044a
    MERGED_INTO = "merged_into"  # source (a problem) was merged into target, WP-044b (0104)
    # WP-058a s5 (REQ-REL-034, -037): source -> a release, and a release -> its parent.
    CAUSED_BY_RELEASE = "caused_by_release"  # an incident, request or problem the release caused
    STARTED_RELEASE = "started_release"  # a record that started the release
    SUB_RELEASE_OF = "sub_release_of"  # a sub-release of a parent release
    # A change raised for an incident, request, problem or release (WP-045a, REQ-CHG-002; 0115).
    CHANGE_FOR = "change_for"
    # A change that is part of a release (WP-058b S1, REQ-REL-033; 0138): change -> release.
    IN_RELEASE = "in_release"
    # A child change or a release -> the change it is part of (WP-045d, REQ-CHG-096; 0133).
    PART_OF_CHANGE = "part_of_change"


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


# --- worklog costs (WP-046a S3, REQ-INC-068) ----------------------------------------------------

CENT = Decimal("0.01")
MONEY_MAX = Decimal("999999999999.99")  # Numeric(14, 2)
COSTS_MAX = 20  # other cost lines on one worklog
COST_NOTE_MAX = 500
_CURRENCY = re.compile(r"^[A-Z]{3}$")


def technician_cost(minutes: int, rate: Decimal) -> Decimal:
    """Minutes at a cost per hour, to the cent (half up): 90 min at 40 is 60.00 (AC1)."""
    return (Decimal(minutes) * rate / Decimal(60)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CostLine:
    """One other cost, in the base currency; paid in another, with what was entered."""

    amount: Decimal
    original_amount: Decimal | None = None
    original_currency: str | None = None
    exchange_rate: Decimal | None = None
    note: str | None = None


def cost_line(  # noqa: PLR0911 - one return per rule, in the order they are checked
    value: Mapping[str, Any], base_currency: str
) -> CostLine | tuple[str, str]:
    """A cost line from its fields, or (field, code) for the first problem.

    In the base currency: `amount`. In another: `original_amount`, `original_currency` and the
    `exchange_rate` the person entered (to the base currency); the amount is computed from them,
    to the cent (no automatic rates, D-164).
    """
    note = value.get("note")
    if note is not None and len(str(note)) > COST_NOTE_MAX:
        return ("note", "value_too_long")
    currency = value.get("original_currency")
    if currency is None or currency == base_currency:
        amount = value.get("amount", value.get("original_amount"))
        if not isinstance(amount, Decimal) or amount < 0 or amount > MONEY_MAX:
            return ("amount", "invalid_value")
        return CostLine(amount.quantize(CENT, rounding=ROUND_HALF_UP), note=note)
    if not isinstance(currency, str) or not _CURRENCY.match(currency):
        return ("original_currency", "invalid_value")
    original, rate = value.get("original_amount"), value.get("exchange_rate")
    if not isinstance(original, Decimal) or original < 0 or original > MONEY_MAX:
        return ("original_amount", "invalid_value")
    if not isinstance(rate, Decimal) or rate <= 0:
        return ("exchange_rate", "required" if rate is None else "invalid_value")
    amount = (original * rate).quantize(CENT, rounding=ROUND_HALF_UP)
    if amount > MONEY_MAX:
        return ("amount", "invalid_value")
    return CostLine(amount, original, currency, rate, note)
