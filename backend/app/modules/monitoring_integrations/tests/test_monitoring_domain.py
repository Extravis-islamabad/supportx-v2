"""The pure rules of reading MonetX (WP-053 S6). No I/O."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.monitoring_integrations.domain.monitoring import (
    ENDED_AFTER,
    Breaker,
    DeviceState,
    HealthState,
    after_run,
    ci_type_for,
    health_of,
    site_for,
)

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("status", "state"),
    [
        ("up", HealthState.UP),
        ("OK", HealthState.UP),
        ("warning", HealthState.DEGRADED),
        ("critical", HealthState.DOWN),
        ("down", HealthState.DOWN),
        ("something new", HealthState.UNKNOWN),
        (None, HealthState.UNKNOWN),
    ],
)
def test_monetx_status_words_map_to_five_codes(status: object, state: HealthState) -> None:
    assert health_of(status) is state


def test_the_breaker_opens_at_its_threshold_and_closes_after_the_cool_down() -> None:
    breaker = Breaker(threshold=3, cool_down=timedelta(seconds=60))
    for _ in range(2):
        breaker = breaker.failed(NOW)
        assert not breaker.is_open(NOW)
    breaker = breaker.failed(NOW)
    assert breaker.is_open(NOW)
    assert breaker.is_open(NOW + timedelta(seconds=59))
    assert not breaker.is_open(NOW + timedelta(seconds=60))  # half-open: one try again
    assert not breaker.succeeded().is_open(NOW)
    assert breaker.succeeded().failures == 0


def test_a_device_is_stale_after_one_missed_run_and_ended_after_three() -> None:
    state, missed = DeviceState.SEEN, 0
    for run in range(1, ENDED_AFTER + 2):
        found = after_run(seen=False, missed_runs=missed, state=state)
        state, missed = found.state, found.missed_runs
        if run < ENDED_AFTER:
            assert (state, found.retire) == (DeviceState.STALE, False)
        elif run == ENDED_AFTER:
            assert (state, found.retire) == (DeviceState.ENDED, True)  # retired once
        else:
            assert (state, found.retire) == (DeviceState.ENDED, False)  # never twice
    back = after_run(seen=True, missed_runs=missed, state=state)
    assert (back.state, back.missed_runs, back.retire) == (DeviceState.SEEN, 0, False)


def test_the_site_map_maps_a_group_or_nothing() -> None:
    site_map = {"DC-1": "a0000000-0000-7000-8000-000000000001", "empty": ""}
    assert site_for(site_map, "DC-1") == "a0000000-0000-7000-8000-000000000001"
    assert site_for(site_map, "DC-2") is None
    assert site_for(site_map, "empty") is None
    assert site_for(site_map, None) is None


def test_device_kinds_become_built_in_ci_types() -> None:
    assert ci_type_for("Router") == "network_device"
    assert ci_type_for("vm") == "server"
    assert ci_type_for("printer") == "hardware"
