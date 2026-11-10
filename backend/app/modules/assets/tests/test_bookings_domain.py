"""Bookings ahead: the next free day (WP-049b s1; REQ-AST-032 AC1)."""

from datetime import UTC, datetime, timedelta

from app.modules.assets.domain.bookings import next_free
from app.modules.assets.domain.loans import Period

DAY = datetime(2026, 12, 1, 9, tzinfo=UTC)


def _day(days: int, hours: int = 8) -> Period:
    start = DAY + timedelta(days=days)
    return Period(start, start + timedelta(hours=hours))


def test_the_next_free_day_has_the_same_length_and_skips_held_days() -> None:
    wanted = _day(0, 2)
    assert next_free(wanted, [_day(0)]) == DAY + timedelta(days=1)
    assert next_free(wanted, [_day(0), _day(1), _day(2)]) == DAY + timedelta(days=3)


def test_touching_ends_are_free_and_nothing_free_gives_none() -> None:
    held = [Period(DAY - timedelta(days=1), DAY)]
    assert next_free(_day(0), held) == DAY + timedelta(days=1)  # step one: never the same day
    always = [Period(DAY, DAY + timedelta(days=500))]
    assert next_free(_day(0), always, days=30) is None
