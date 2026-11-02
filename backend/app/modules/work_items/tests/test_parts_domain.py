"""Worklog times and task order (WP-020e; REQ-INC-067, 072): pure rules, no I/O."""

from datetime import UTC, datetime, timedelta

from app.modules.work_items.domain.parts import WorklogProblem, WorklogTimes, moved, worklog_times

START = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)


def test_req_inc_067_ac1_the_end_is_never_before_the_start() -> None:
    assert worklog_times(START, START - timedelta(minutes=1), None) == (
        "ended_at",
        WorklogProblem.END_BEFORE_START,
    )
    assert worklog_times(None, START, None) == ("started_at", WorklogProblem.START_REQUIRED)
    assert worklog_times(START, None, None) == ("ended_at", WorklogProblem.END_OR_DURATION)


def test_req_inc_067_ac2_start_and_duration_fill_the_end_and_back() -> None:
    assert worklog_times(START, None, 45) == WorklogTimes(START, START + timedelta(minutes=45), 45)
    assert worklog_times(START, START + timedelta(hours=2), None) == WorklogTimes(
        START, START + timedelta(hours=2), 120
    )
    assert worklog_times(START, START + timedelta(hours=1), 30) == (
        "minutes",
        WorklogProblem.DURATION_MISMATCH,
    )
    assert worklog_times(START, None, 0) == ("minutes", WorklogProblem.DURATION_RANGE)
    assert worklog_times(START, START, None) == ("ended_at", WorklogProblem.DURATION_RANGE)


def test_req_inc_072_ac2_moving_a_task_one_place() -> None:
    assert moved(["a", "b", "c"], 2, -1) == ["a", "c", "b"]
    assert moved(["a", "b", "c"], 0, 1) == ["b", "a", "c"]
    assert moved(["a", "b", "c"], 0, -1) is None
    assert moved(["a", "b", "c"], 2, 1) is None
