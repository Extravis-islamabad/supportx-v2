from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.shared.clock import Clock, FrozenClock, SystemClock, system_clock


def test_system_clock_returns_aware_utc_now() -> None:
    before = datetime.now(UTC)
    now = SystemClock().now()
    assert now.tzinfo is UTC
    assert before <= now <= datetime.now(UTC)
    assert isinstance(system_clock, SystemClock)


def test_frozen_clock_stays_put_until_moved() -> None:
    start = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    clock: Clock = FrozenClock(start)
    assert clock.now() == start
    assert clock.now() == start


def test_frozen_clock_advances_and_jumps() -> None:
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    assert clock.advance(timedelta(hours=4)) == datetime(2026, 1, 1, 4, tzinfo=UTC)
    clock.set(datetime(2027, 6, 1, tzinfo=UTC))
    assert clock.now() == datetime(2027, 6, 1, tzinfo=UTC)


def test_frozen_clock_normalises_to_utc() -> None:
    gulf = timezone(timedelta(hours=4))
    clock = FrozenClock(datetime(2026, 1, 1, 13, 0, tzinfo=gulf))
    assert clock.now() == datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    assert clock.now().tzinfo is UTC


def test_frozen_clock_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FrozenClock(datetime(2026, 1, 1))  # noqa: DTZ001 - the naive value is the point
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="timezone-aware"):
        clock.set(datetime(2026, 1, 2))  # noqa: DTZ001 - as above
