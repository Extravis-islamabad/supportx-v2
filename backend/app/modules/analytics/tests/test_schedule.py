"""When scheduled reports run (REQ-RPT-052)."""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from app.modules.analytics.domain.schedule import Frequency, Recurrence

RIYADH = "Asia/Riyadh"
LONDON = "Europe/London"


def _local(instant: datetime | None, zone: str) -> str:
    assert instant is not None
    return instant.astimezone(ZoneInfo(zone)).strftime("%a %Y-%m-%d %H:%M")


def test_req_rpt_052_ac1_weekly_monday_seven_in_riyadh() -> None:
    weekly = Recurrence(Frequency.WEEKLY, time(7, 0), RIYADH, date(2026, 10, 1), weekdays=(0,))
    first = weekly.next_after(datetime(2026, 10, 28, 12, tzinfo=UTC))  # a Wednesday
    assert _local(first, RIYADH) == "Mon 2026-11-02 07:00"
    assert first is not None
    assert _local(weekly.next_after(first), RIYADH) == "Mon 2026-11-09 07:00"


def test_req_rpt_052_ac1_same_local_time_across_a_daylight_saving_change() -> None:
    weekly = Recurrence(Frequency.WEEKLY, time(7, 0), LONDON, date(2026, 10, 1), weekdays=(0,))
    before = weekly.next_after(datetime(2026, 10, 20, tzinfo=UTC))
    after = weekly.next_after(datetime(2026, 10, 27, tzinfo=UTC))  # clocks went back on 25 Oct
    assert _local(before, LONDON) == "Mon 2026-10-26 07:00"
    assert _local(after, LONDON) == "Mon 2026-11-02 07:00"
    assert before is not None
    assert before.astimezone(UTC).hour == 7  # 26 Oct is already GMT: 07:00 local is 07:00 UTC


def test_a_time_inside_the_spring_gap_runs_right_after_it() -> None:
    daily = Recurrence(Frequency.DAILY, time(1, 30), LONDON, date(2026, 3, 1))
    run = daily.next_after(datetime(2026, 3, 28, 12, tzinfo=UTC))
    assert _local(run, LONDON) == "Sun 2026-03-29 02:30"  # 01:30 does not exist that day


def test_daily_on_chosen_weekdays_monthly_on_a_date_and_the_end_date() -> None:
    workdays = Recurrence(
        Frequency.DAILY, time(8, 0), RIYADH, date(2026, 10, 1), weekdays=(6, 0, 1, 2, 3)
    )
    friday = datetime(2026, 10, 30, 6, tzinfo=UTC)  # Friday 09:00 in Riyadh
    assert _local(workdays.next_after(friday), RIYADH) == "Sun 2026-11-01 08:00"
    monthly = Recurrence(Frequency.MONTHLY, time(7, 0), RIYADH, date(2026, 10, 1), day_of_month=1)
    assert _local(monthly.next_after(friday), RIYADH) == "Sun 2026-11-01 07:00"
    ended = Recurrence(
        Frequency.DAILY, time(7, 0), RIYADH, date(2026, 10, 1), end=date(2026, 10, 31)
    )
    assert ended.next_after(datetime(2026, 10, 31, 6, tzinfo=UTC)) is None  # REQ-RPT-052 AC3


def test_invalid_recurrences_name_their_problem() -> None:
    assert Recurrence(Frequency.WEEKLY, time(7), RIYADH, date(2026, 1, 1)).problems() == [
        ("weekdays", "one_day_required")
    ]
    assert ("day_of_month", "out_of_range") in Recurrence(
        Frequency.MONTHLY, time(7), RIYADH, date(2026, 1, 1), day_of_month=31
    ).problems()
    assert ("time_zone", "invalid_choice") in Recurrence(
        Frequency.DAILY, time(7), "Mars/Base", date(2026, 1, 1)
    ).problems()
    assert ("end_date", "end_before_start") in Recurrence(
        Frequency.DAILY, time(7), RIYADH, date(2026, 2, 1), end=date(2026, 1, 1)
    ).problems()
