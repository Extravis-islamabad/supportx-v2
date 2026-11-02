"""The published business-time table (REQ-SLA-014 AC1), read from docs and checked row by row.

The table lives in `docs/architecture/sla-business-time.md` so people can read the rules; this
test makes it binding. Plus a seeded property check: `between(a, add(a, s)) == s` everywhere.
"""

import random
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.modules.sla.domain.calendar import (
    Calendar,
    CalendarKind,
    HolidayPart,
    Period,
    SpecialHours,
    parse_hhmm,
    period_errors,
    special_hours_problems,
    zone_or_none,
)

TABLE = Path(__file__).resolve().parents[5] / "docs" / "architecture" / "sla-business-time.md"
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MIN_CASES = 50  # REQ-SLA-014 AC1


def _rows(section: str) -> list[list[str]]:
    text = TABLE.read_text(encoding="utf-8")
    body = text.split(f"## {section}", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in body.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not line.startswith("|") or set(cells[0]) <= {"-"} or cells[0] in {"Code", "#"}:
            continue
        rows.append(cells)
    return rows


def _days(spec: str) -> list[int]:
    first, _, last = spec.partition("-")
    start = DAYS.index(first)
    end = DAYS.index(last) if last else start
    return [(start + i) % 7 for i in range((end - start) % 7 + 1)]


def _periods(week: str) -> list[Period]:
    periods: list[Period] = []
    for group in week.split(";"):
        days, _, times = group.strip().partition(" ")
        for span in times.split(","):
            start, end = (parse_hhmm(t) for t in span.strip().split("-"))
            periods.extend(Period(day, start, end) for day in _days(days))
    return periods


def _special(text: str) -> tuple[SpecialHours, ...]:
    ranges = []
    for item in filter(None, (r.strip() for r in text.split(" + "))):
        dates, _, week = item.partition(": ")
        first, _, last = dates.partition("..")
        ranges.append(
            SpecialHours(date.fromisoformat(first), date.fromisoformat(last), tuple(_periods(week)))
        )
    assert special_hours_problems(ranges) == [], text
    return tuple(ranges)


def _calendar(zone_name: str, week: str, holidays: str, special: str) -> Calendar:
    zone = zone_or_none(zone_name)
    assert zone is not None, zone_name
    if week == "around the clock":
        return Calendar(zone=zone, kind=CalendarKind.AROUND_THE_CLOCK)
    periods = _periods(week)
    assert period_errors(periods) == [], week
    marked: dict[date, HolidayPart] = {}
    for entry in filter(None, (h.strip() for h in holidays.split(";"))):
        day, _, part = entry.partition(" ")
        marked[date.fromisoformat(day)] = HolidayPart(part or "full")
    return Calendar(zone=zone, periods=tuple(periods), holidays=marked, special=_special(special))


CALENDARS = {
    code: _calendar(zone, week, holidays, special)
    for code, zone, week, holidays, special in _rows("Calendars")
}
CASES = _rows("Cases")


def _local(calendar: Calendar, text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=calendar.zone)


def _seconds(text: str) -> int:
    if text == "0":
        return 0
    sign = -1 if text.startswith("-") else 1
    parts = {unit: int(number) for number, unit in re.findall(r"(\d+)([hm])", text)}
    assert parts, text
    return sign * (parts.get("h", 0) * 3600 + parts.get("m", 0) * 60)


def test_the_table_has_enough_cases_and_unique_numbers() -> None:
    numbers = [int(row[0]) for row in CASES]
    assert len(numbers) >= MIN_CASES
    assert numbers == list(range(1, len(numbers) + 1))


@pytest.mark.parametrize("row", CASES, ids=[f"case-{row[0]}" for row in CASES])
def test_case(row: list[str]) -> None:
    _, code, check, start_text, amount, expected, why = row
    calendar = CALENDARS[code]
    start = _local(calendar, start_text)
    if check == "add":
        got = calendar.add(start, _seconds(amount))
        assert got == _local(calendar, expected), (why, got.astimezone(calendar.zone))
        assert got.tzinfo is UTC
    elif check == "between":
        assert calendar.between(start, _local(calendar, amount)) == _seconds(expected), why
    elif check == "working":
        assert calendar.working_at(start) is (expected == "yes"), why
    else:  # pragma: no cover - a typo in the table
        pytest.fail(f"unknown check {check!r}")


@pytest.mark.parametrize("code", sorted(CALENDARS))
def test_between_undoes_add(code: str) -> None:
    """Property: business time added and then counted back is exact, from any start."""
    calendar = CALENDARS[code]
    rng = random.Random(f"sla-{code}")  # noqa: S311 - seeded test samples, not security
    origin = datetime(2026, 1, 1, tzinfo=UTC)
    for _ in range(300):
        start = origin + timedelta(seconds=rng.randrange(0, 3 * 366 * 86400))
        seconds = rng.choice((1, 59, 60, 3600, rng.randrange(1, 40 * 3600)))
        due = calendar.add(start, seconds)
        assert calendar.between(start, due) == seconds, (start, seconds)
        assert due > start
        # The due moment itself is the end of counted time: one second earlier is still short.
        assert calendar.between(start, due - timedelta(seconds=1)) == seconds - 1


def test_results_do_not_depend_on_the_zone_of_the_input() -> None:
    calendar = CALENDARS["R-ST"]
    riyadh = _local(calendar, "2026-11-05 16:00")
    assert calendar.add(riyadh, 7200) == calendar.add(riyadh.astimezone(UTC), 7200)


def test_a_calendar_with_no_week_cannot_promise_a_due_date() -> None:
    empty = Calendar(zone=CALENDARS["K-MF"].zone)
    with pytest.raises(ValueError, match="no_working_time"):
        empty.add(datetime(2026, 11, 2, tzinfo=UTC), 60)
    assert empty.between(datetime(2026, 11, 2, tzinfo=UTC), datetime(2026, 11, 9, tzinfo=UTC)) == 0


def test_naive_instants_are_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        CALENDARS["K-MF"].add(datetime(2026, 11, 2, 9), 60)  # noqa: DTZ001 - the point of the test
