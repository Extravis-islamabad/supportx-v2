"""Which cost per hour is in force, and which may still change (REQ-INC-068). No I/O."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.identity_access.domain.cost_rates import (
    RateState,
    in_force,
    require_aware,
    state_of,
    superseded,
)

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
DAY = timedelta(days=1)


@dataclass(frozen=True)
class R:
    effective_from: datetime
    name: str = ""


def test_the_latest_started_rate_is_in_force() -> None:
    old, current, upcoming = R(NOW - 30 * DAY, "old"), R(NOW - DAY, "current"), R(NOW + DAY, "up")
    rates = [upcoming, old, current]
    assert in_force(rates, NOW) is current
    assert in_force(rates, NOW - 10 * DAY) is old
    assert in_force(rates, NOW + 2 * DAY) is upcoming
    assert in_force(rates, NOW - 31 * DAY) is None  # before the first one
    assert in_force([], NOW) is None
    # A rate starting at exactly the moment is in force at it.
    assert in_force(rates, NOW - DAY) is current


def test_states_now() -> None:
    old, current, upcoming = R(NOW - 30 * DAY), R(NOW - DAY), R(NOW + DAY)
    rates = [upcoming, current, old]
    assert [state_of(r, rates, NOW) for r in rates] == [
        RateState.FUTURE,
        RateState.CURRENT,
        RateState.PAST,
    ]


def test_a_rate_is_superseded_once_a_later_one_has_started() -> None:
    later_started, later_upcoming = R(NOW - DAY), R(NOW + DAY)
    assert superseded(NOW - 30 * DAY, [later_started], NOW)
    assert not superseded(NOW - 30 * DAY, [later_upcoming], NOW)
    assert not superseded(NOW - DAY, [R(NOW - 30 * DAY)], NOW)  # only an earlier one


def test_a_naive_moment_is_refused() -> None:
    naive = datetime(2026, 11, 12, 9, 0)  # noqa: DTZ001 - the case under test
    with pytest.raises(ValueError, match="timezone-aware"):
        require_aware(naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        in_force([R(NOW)], naive)
