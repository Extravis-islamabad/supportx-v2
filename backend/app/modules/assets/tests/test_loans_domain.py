"""Loan periods and status (REQ-AST-030, 031), without I/O."""

from datetime import UTC, datetime, timedelta

from app.modules.assets.domain.loans import Period, any_overlap, loan_status, overlaps

T0 = datetime(2026, 11, 6, 9, tzinfo=UTC)
DAY = timedelta(days=1)


def test_overlapping_periods_are_found_and_touching_ends_are_not() -> None:
    week = Period(T0, T0 + 7 * DAY)
    assert overlaps(week, Period(T0 + 6 * DAY, T0 + 9 * DAY))
    assert overlaps(week, Period(T0 - DAY, T0 + DAY))
    assert not overlaps(week, Period(T0 + 7 * DAY, T0 + 8 * DAY))  # starts as the other ends
    assert any_overlap(Period(T0 + DAY, T0 + 2 * DAY), [week])
    assert not any_overlap(Period(T0 + 8 * DAY, T0 + 9 * DAY), [week])


def test_a_loan_is_open_overdue_or_closed() -> None:
    due = T0 + DAY
    assert loan_status(due_at=due, outstanding=2, now=T0) == "open"
    assert loan_status(due_at=due, outstanding=1, now=due) == "overdue"
    assert loan_status(due_at=due, outstanding=0, now=due + DAY) == "closed"
