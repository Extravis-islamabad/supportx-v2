"""A person's cost per hour by date: which rate is in force, and which may change. Pure, no I/O.

A rate starts at `effective_from` and holds until the next live rate starts. At any moment the
rate in force is the latest one starting at or before it; before the first one there is none.
A rate whose successor has started is superseded: it stays as it was (costs worked out with it
keep it), and a correction is a new rate.
"""

from collections.abc import Iterable, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class RateState(StrEnum):
    """Where a rate stands now (labels `people.cost_rate.state.<code>`)."""

    CURRENT = "current"
    FUTURE = "future"
    PAST = "past"


class Dated(Protocol):
    """A rate's start."""

    @property
    def effective_from(self) -> datetime:
        """When the rate starts."""


def require_aware(at: datetime) -> None:
    """A moment must carry its time zone: a naive one would be read in nobody knows which."""
    if at.tzinfo is None or at.utcoffset() is None:
        msg = "the moment must be timezone-aware"
        raise ValueError(msg)


def in_force[RateT: Dated](rates: Iterable[RateT], at: datetime) -> RateT | None:
    """The latest rate starting at or before `at` (None before the first one)."""
    require_aware(at)
    started = [r for r in rates if r.effective_from <= at]
    return max(started, key=lambda r: r.effective_from) if started else None


def state_of(rate: Dated, rates: Sequence[Dated], now: datetime) -> RateState:
    """Upcoming, in force, or superseded by a later rate that has started."""
    if rate.effective_from > now:
        return RateState.FUTURE
    current = in_force(rates, now)
    return RateState.CURRENT if current is rate else RateState.PAST


def superseded(start: datetime, others: Iterable[Dated], now: datetime) -> bool:
    """Whether a rate starting at `start` is past: another rate after it has started by now."""
    return any(start < other.effective_from <= now for other in others)
