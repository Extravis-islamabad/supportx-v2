"""Which downtime changes are a downtime *starting* (WP-053 S5d's downtime_started trigger)."""

import uuid

import pytest

from app.modules.automation import TriggerEvent
from app.modules.cmdb.service.automation import RECORD_TYPE, _downtime_started

CI = uuid.uuid4()


@pytest.mark.parametrize(
    ("change", "previous"),
    [
        ("state", "scheduled"),  # the sweep
        ("added", None),  # recorded already under way
        ("updated", "scheduled"),  # an edit (or a mirrored work item) moved its start (lane A)
    ],
)
def test_becoming_active_is_a_start(change: str, previous: str | None) -> None:
    payload = {"change": change, "state": "active", "previous_state": previous}
    [event] = _downtime_started(payload, CI)
    assert (event.record_type, event.record_id) == (RECORD_TYPE, CI)
    assert event.event is TriggerEvent.DOWNTIME_STARTED
    assert list(event.changed) == ["downtimes"]  # nothing about the downtime itself


@pytest.mark.parametrize(
    ("change", "state"),
    [
        ("state", "completed"),  # ending is not starting
        ("added", "scheduled"),  # recorded for later: it starts when the sweep moves it
        ("updated", "active"),  # an edit while active did not move it
        ("removed", "active"),
    ],
)
def test_anything_else_is_not(change: str, state: str) -> None:
    previous = "active" if state == "active" else "scheduled"
    payload = {"change": change, "state": state, "previous_state": previous}
    assert _downtime_started(payload, CI) == []


@pytest.mark.parametrize(
    ("change", "fires"), [("state", True), ("added", True), ("updated", False)]
)
def test_an_event_from_before_previous_state_keeps_the_old_rule(change: str, fires: bool) -> None:
    assert bool(_downtime_started({"change": change, "state": "active"}, CI)) is fires
