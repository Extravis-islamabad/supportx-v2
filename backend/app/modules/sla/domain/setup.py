"""Calendar set-up rules (WP-025 session 1): stored weeks, presets, holidays as dates.

Pure Python. The service stores a week as JSON (`[{"weekday", "start", "end"}]`, times "HH:MM")
and holidays as rows; this module turns both into a `Calendar` for the maths, and checks what
an admin sends. Rules return codes, never messages.
"""

import enum
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.modules.sla.domain.calendar import (
    MINUTES_PER_DAY,
    Calendar,
    CalendarKind,
    HolidayPart,
    Period,
    SpecialHours,
    format_hhmm,
    parse_hhmm,
    period_errors,
    zone_or_none,
)

MAX_PERIODS = 28  # four periods a day is plenty; the limit keeps a stored week small
MAX_HOLIDAY_DAYS = 366


class SystemCalendar(enum.StrEnum):
    """The calendars every tenant has (REQ-SLA-010: "around the clock" always exists)."""

    AROUND_THE_CLOCK = "around_the_clock"
    OPERATING_HOURS = "operating_hours"  # the default operating hours (D-115 D2)


class WeekPreset(enum.StrEnum):
    """The working weeks offered in one click at setup (D-115 D2)."""

    MON_FRI = "mon_fri"  # Monday-Friday 09:00-18:00, the default
    SUN_THU = "sun_thu"  # Sunday-Thursday 08:00-17:00
    MON_SAT = "mon_sat"  # Monday-Saturday 09:00-18:00


class HolidayOrigin(enum.StrEnum):
    """Where a holiday row came from."""

    MANUAL = "manual"
    IMPORT = "import"  # an iCalendar file
    COPY = "copy"  # copied to the next year: check the date (REQ-SLA-012 AC3)


_PRESETS: Mapping[WeekPreset, tuple[Sequence[int], str, str]] = {
    WeekPreset.MON_FRI: ((0, 1, 2, 3, 4), "09:00", "18:00"),
    WeekPreset.SUN_THU: ((6, 0, 1, 2, 3), "08:00", "17:00"),
    WeekPreset.MON_SAT: ((0, 1, 2, 3, 4, 5), "09:00", "18:00"),
}
DEFAULT_PRESET = WeekPreset.MON_FRI
DEFAULT_ZONE = "UTC"  # only when the tenant's default site has no time zone


def preset_week(preset: WeekPreset) -> list[dict[str, Any]]:
    """The stored week of a preset."""
    days, start, end = _PRESETS[preset]
    return [{"weekday": day, "start": start, "end": end} for day in sorted(days)]


def periods_of(week: Iterable[Mapping[str, Any]]) -> tuple[Period, ...]:
    """The periods of a stored (already checked) week."""
    return tuple(
        sorted(
            Period(int(p["weekday"]), parse_hhmm(str(p["start"])), parse_hhmm(str(p["end"])))
            for p in week
        )
    )


def week_problems(week: Sequence[Mapping[str, Any]]) -> list[str]:
    """Codes for a week an admin sent: shape, times, overlaps, or no working time at all."""
    if not week:
        return ["week_empty"]
    if len(week) > MAX_PERIODS:
        return ["week_too_many_periods"]
    periods: list[Period] = []
    for item in week:
        try:
            start, end = parse_hhmm(str(item["start"])), parse_hhmm(str(item["end"]))
            weekday = int(item["weekday"])
        except (KeyError, TypeError, ValueError):
            return ["period_time_invalid"]
        if start == MINUTES_PER_DAY:  # "24:00" ends a period, never starts one
            return ["period_time_invalid"]
        periods.append(Period(weekday, start, end))
    return period_errors(periods)


def normal_week(week: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """A checked week as stored: sorted, times written "HH:MM"."""
    return [
        {"weekday": p.weekday, "start": format_hhmm(p.start), "end": format_hhmm(p.end)}
        for p in periods_of(week)
    ]


@dataclass(frozen=True)
class HolidayDates:
    """One holiday row as the maths needs it."""

    starts_on: date
    ends_on: date
    part: HolidayPart = HolidayPart.FULL


def holiday_problems(starts_on: date, ends_on: date, part: HolidayPart) -> list[str]:
    """Codes for a holiday: the range order and length, and half days on one day only."""
    if ends_on < starts_on:
        return ["holiday_range_order"]
    if (ends_on - starts_on).days >= MAX_HOLIDAY_DAYS:
        return ["holiday_range_too_long"]
    if part is not HolidayPart.FULL and ends_on != starts_on:
        return ["half_day_single_date"]
    return []


def holiday_map(holidays: Iterable[HolidayDates]) -> dict[date, HolidayPart]:
    """Each holiday date with its part; a full day wins over a half day on the same date."""
    days: dict[date, HolidayPart] = {}
    for holiday in holidays:
        day = holiday.starts_on
        while day <= holiday.ends_on:
            if days.get(day) is not HolidayPart.FULL:
                previous = days.get(day)
                # Morning off on one list and afternoon off on another: the whole day is off.
                both_halves = previous is not None and previous is not holiday.part
                days[day] = HolidayPart.FULL if both_halves else holiday.part
            day += timedelta(days=1)
    return days


@dataclass(frozen=True)
class SpecialRange:
    """Stored special date-range hours: first and last day and their week (stored form)."""

    starts_on: date
    ends_on: date
    week: Sequence[Mapping[str, Any]]


def build_calendar(
    *,
    kind: str,
    time_zone: str,
    week: Iterable[Mapping[str, Any]],
    holidays: Iterable[HolidayDates],
    special: Iterable[SpecialRange] = (),
) -> Calendar:
    """The maths calendar of a stored calendar, its date-range hours and its holidays."""
    if kind == CalendarKind.AROUND_THE_CLOCK:
        return Calendar.around_the_clock()
    zone = zone_or_none(time_zone) or zone_or_none(DEFAULT_ZONE)
    assert zone is not None  # noqa: S101 - UTC always exists (tzdata ships, D-115)
    return Calendar(
        zone=zone,
        periods=periods_of(week),
        holidays=holiday_map(holidays),
        special=tuple(SpecialHours(r.starts_on, r.ends_on, periods_of(r.week)) for r in special),
    )


def next_year(day: date) -> date:
    """The same day next year; 29 February becomes 28 February."""
    try:
        return day.replace(year=day.year + 1)
    except ValueError:
        return day.replace(year=day.year + 1, day=28)
