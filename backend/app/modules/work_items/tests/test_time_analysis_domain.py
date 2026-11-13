"""Time analysis maths (WP-046a S3, REQ-INC-071), without I/O."""

from datetime import UTC, datetime, timedelta

from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.time_analysis import Step, analyse, initial_values

T0 = datetime(2026, 11, 12, 8, 0, tzinfo=UTC)
CATEGORIES = {
    "new": StatusCategory.OPEN,
    "in_progress": StatusCategory.OPEN,
    "awaiting_requester": StatusCategory.PAUSED,
    "resolved": StatusCategory.RESOLVED,
    "closed": StatusCategory.CLOSED,
}


def hours(n: float) -> datetime:
    return T0 + timedelta(hours=n)


def calendar(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds())


def status(at: float, old: str, new: str) -> Step:
    return Step(hours(at), "status", old, new)


def test_ac1_two_hours_in_progress_and_one_paused_show_both() -> None:
    steps = [
        status(0, "new", "in_progress"),
        status(2, "in_progress", "awaiting_requester"),
        status(3, "awaiting_requester", "resolved"),
    ]
    found = analyse(
        T0,
        hours(5),
        initial_values({"status": "resolved"}, steps),
        steps,
        category=CATEGORIES.__getitem__,
        measure=calendar,
    )
    assert found.by_status == {
        "in_progress": 2 * 3600,
        "awaiting_requester": 3600,
        "resolved": 2 * 3600,
    }
    assert (found.open_seconds, found.paused_seconds) == (3 * 3600, 3600)


def test_ac3_reopening_keeps_earlier_time_and_adds_new_time() -> None:
    steps = [
        status(1, "new", "resolved"),
        status(4, "resolved", "in_progress"),  # reopened
    ]
    found = analyse(
        T0,
        hours(6),
        initial_values({"status": "in_progress"}, steps),
        steps,
        category=CATEGORIES.__getitem__,
        measure=calendar,
    )
    assert found.by_status == {"new": 3600, "resolved": 3 * 3600, "in_progress": 2 * 3600}
    assert found.open_seconds == 3 * 3600


def test_group_and_technician_time_count_only_while_open() -> None:
    steps = [
        Step(hours(1), "group_id", None, "g1"),
        Step(hours(1), "technician_id", None, "t1"),
        Step(hours(3), "group_id", "g1", "g2"),
        status(4, "in_progress", "closed"),
    ]
    found = analyse(
        T0,
        hours(8),
        initial_values({"status": "closed", "group_id": "g2", "technician_id": "t1"}, steps),
        steps,
        category=CATEGORIES.__getitem__,
        measure=calendar,
    )
    assert found.by_group == {None: 3600, "g1": 2 * 3600, "g2": 3600}
    assert found.by_technician == {None: 3600, "t1": 3 * 3600}


def test_ac2_the_measure_decides_business_or_calendar_hours() -> None:
    def business(a: datetime, b: datetime) -> int:  # 09:00-17:00 only, as a calendar would
        total = 0
        moment = a
        while moment < b:
            nxt = min(b, moment + timedelta(minutes=1))
            if 9 <= moment.hour < 17:
                total += int((nxt - moment).total_seconds())
            moment = nxt
        return total

    found = analyse(
        T0,
        hours(4),  # 08:00 to 12:00
        {"status": "in_progress"},
        [],
        category=CATEGORIES.__getitem__,
        measure=business,
    )
    assert found.open_seconds == 3 * 3600  # 09:00-12:00


def test_no_changes_means_the_current_values_all_along() -> None:
    assert initial_values({"status": "new", "group_id": None}, []) == {
        "status": "new",
        "group_id": None,
        "technician_id": None,
    }


def test_a_closed_spell_never_grows_and_a_reopen_counts_again() -> None:
    steps = [
        status(1, "new", "closed"),
        status(5, "closed", "in_progress"),  # reopened
        status(6, "in_progress", "closed"),
    ]
    found = analyse(
        T0,
        hours(100),  # closed for days since
        initial_values({"status": "closed"}, steps),
        steps,
        category=CATEGORIES.__getitem__,
        measure=calendar,
    )
    assert found.by_status == {"new": 3600, "in_progress": 3600}
    assert found.open_seconds == 2 * 3600
