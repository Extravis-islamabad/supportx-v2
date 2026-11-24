"""Which downtime changes are a downtime *starting* (WP-053 S5d's downtime_started trigger)."""

import uuid

import pytest

from app.modules.automation import TriggerEvent
from app.modules.cmdb.service.automation import RECORD_TYPE, _downtime_started

CI = uuid.uuid4()


@pytest.mark.parametrize("change", ["state", "added"])
def test_becoming_active_is_a_start(change: str) -> None:
    [event] = _downtime_started({"change": change, "state": "active"}, CI)
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
    assert _downtime_started({"change": change, "state": state}, CI) == []
