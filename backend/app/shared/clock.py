"""Clock abstraction (WP-004).

Services ask a `Clock` for the time instead of calling `datetime.now()`, so tests can freeze and
advance time deterministically (SLA timers, expiries, audit timestamps). All times are timezone-
aware UTC, matching the `timestamptz` convention (architecture.md §7.1).
"""

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    """Source of the current time."""

    def now(self) -> datetime:
        """Current time, timezone-aware UTC."""
        ...


class SystemClock:
    """The real wall clock."""

    def now(self) -> datetime:
        """Current time, timezone-aware UTC."""
        return datetime.now(UTC)


class FrozenClock:
    """A clock that only moves when told to. For tests."""

    def __init__(self, at: datetime) -> None:
        self._now = _require_aware(at)

    def now(self) -> datetime:
        """The frozen time."""
        return self._now

    def set(self, at: datetime) -> None:
        """Jump to `at`."""
        self._now = _require_aware(at)

    def advance(self, delta: timedelta) -> datetime:
        """Move forward by `delta` and return the new time."""
        self._now += delta
        return self._now


def _require_aware(at: datetime) -> datetime:
    if at.tzinfo is None or at.utcoffset() is None:
        msg = "FrozenClock needs a timezone-aware datetime"
        raise ValueError(msg)
    return at.astimezone(UTC)


system_clock: Clock = SystemClock()
