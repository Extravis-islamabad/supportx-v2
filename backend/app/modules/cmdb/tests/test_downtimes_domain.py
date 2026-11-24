"""CI downtimes, pure (WP-053 S5b; REQ-CMDB-020): state from the times, the hand form's checks,
and which events are stale."""

from datetime import UTC, datetime, timedelta

from app.modules.cmdb.domain import downtimes as d
from app.modules.cmdb.domain.downtimes import CiDowntimeState

T0 = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)


def test_the_state_follows_the_times() -> None:
    assert d.state_at(T0, T0 + HOUR, T0 - HOUR) is CiDowntimeState.SCHEDULED
    assert d.state_at(T0, T0 + HOUR, T0) is CiDowntimeState.ACTIVE  # active AT the start (AC1)
    assert d.state_at(T0, T0 + HOUR, T0 + HOUR / 2) is CiDowntimeState.ACTIVE
    assert d.state_at(T0, T0 + HOUR, T0 + HOUR) is CiDowntimeState.COMPLETED  # over at the end
    assert d.state_at(T0, None, T0 + 100 * HOUR) is CiDowntimeState.ACTIVE  # open-ended


def test_the_hand_form_refuses_bad_times_and_long_words() -> None:
    assert d.check_manual(T0, T0 + HOUR, "Disk swap") == []
    assert d.check_manual(T0, None, None) == []
    codes = {(p.field, p.code) for p in d.check_manual(T0, T0 - HOUR, None)}
    assert codes == {("ends_at", "end_before_start")}
    assert {p.code for p in d.check_manual(T0, T0, None)} == {"end_before_start"}
    too_long = d.check_manual(T0, T0 + d.LONGEST + HOUR, None)
    assert [p.code for p in too_long] == ["downtime_too_long"]
    naive = d.check_manual(T0.replace(tzinfo=None), None, None)
    assert [(p.field, p.code) for p in naive] == [("starts_at", "timezone_required")]
    wordy = d.check_manual(T0, None, "x" * (d.DESCRIPTION_MAX + 1))
    assert [(p.field, p.code) for p in wordy] == [("description", "value_too_long")]


def test_an_event_at_or_below_the_stored_version_is_stale() -> None:
    assert not d.is_stale(None, 1)  # nothing applied yet
    assert not d.is_stale(3, 4)
    assert d.is_stale(4, 4)  # replayed
    assert d.is_stale(5, 4)  # out of order


def test_only_changes_releases_and_incidents_send_downtimes() -> None:
    assert set(d.SOURCE_OF_TYPE) == {"change", "release", "incident"}
    assert d.CiDowntimeSource.MANUAL not in d.SOURCE_OF_TYPE.values()
