"""Loans: the pure rules (WP-049a s5; REQ-AST-029, 030, 031). No I/O."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

LOAN_STATUSES = ("open", "overdue", "closed")
RETURN_OUTCOMES = ("in_stock", "in_repair")


@dataclass(frozen=True, slots=True)
class Period:
    """A loan's time: from when to when it is due (an open end never overlaps by itself)."""

    starts_at: datetime
    due_at: datetime


def overlaps(one: Period, other: Period) -> bool:
    """Two loan periods share any moment (REQ-AST-030 AC3); touching ends do not overlap."""
    return one.starts_at < other.due_at and other.starts_at < one.due_at


def any_overlap(new: Period, taken: Iterable[Period]) -> bool:
    """Whether a new loan's period overlaps one the asset is already out for."""
    return any(overlaps(new, period) for period in taken)


def loan_status(*, due_at: datetime, outstanding: int, now: datetime) -> str:
    """Closed when nothing is outstanding (031 AC2); overdue once due with items out (030 AC2)."""
    if outstanding == 0:
        return "closed"
    return "overdue" if now >= due_at else "open"
