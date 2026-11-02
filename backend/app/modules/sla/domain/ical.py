"""Holiday import from an iCalendar file (REQ-SLA-012 AC2; `icalendar`, D-115 D9).

Imported files are untrusted (D-115): the size and line counts are checked **before** parsing,
the parser's errors become a code, and every event either becomes a holiday or is reported as
skipped with a reason. Nothing here raises on bad input except `IcalRefused` for the whole file.

- An all-day event (`DTSTART;VALUE=DATE`) is a holiday from its start date to the day before
  its `DTEND` (iCalendar ends are exclusive); without `DTEND` it is one day.
- A timed event counts by the dates it touches in its own zone.
- A repeating event (`RRULE`, `RDATE`) is skipped: a holiday that moves each year (Eid) cannot
  be expanded by a rule, so each year's date must be in the file.
"""

import enum
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import icalendar

MAX_BYTES = 1_000_000
MAX_LINES = 20_000
MAX_EVENTS = 1_000
MAX_DAYS = 366
NAME_MAX = 200
ICAL_TOO_LARGE = "ical_too_large"
ICAL_TOO_MANY_LINES = "ical_too_many_lines"
ICAL_NOT_UTF8 = "ical_not_utf8"
ICAL_INVALID = "ical_invalid"


class IcalSkip(enum.StrEnum):
    """Why an event in an imported file did not become a holiday."""

    REPEATING = "repeating"
    NO_DATE = "no_date"
    BAD_RANGE = "bad_range"
    TOO_LONG = "too_long"
    TOO_MANY = "too_many"
    NO_NAME = "no_name"


class IcalRefused(ValueError):
    """The whole file is refused (too big, too many lines, not iCalendar)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ImportedHoliday:
    """One holiday read from the file."""

    name: str
    starts_on: date
    ends_on: date


@dataclass(frozen=True)
class SkippedEvent:
    """An event that was not imported, with its name (if any) and the reason."""

    name: str | None
    reason: IcalSkip


@dataclass
class IcalResult:
    """What the file gives: holidays in file order, and what was skipped."""

    holidays: list[ImportedHoliday] = field(default_factory=list)
    skipped: list[SkippedEvent] = field(default_factory=list)


def _day(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _name(event: icalendar.Event) -> str | None:
    summary = event.get("SUMMARY")
    text = " ".join(str(summary).split()) if summary is not None else ""
    return text[:NAME_MAX] or None


def parse_holidays(data: bytes) -> IcalResult:
    """Holidays from an iCalendar file; `IcalRefused` when the file as a whole is not usable."""
    if len(data) > MAX_BYTES:
        raise IcalRefused(ICAL_TOO_LARGE)
    if data.count(b"\n") + 1 > MAX_LINES:
        raise IcalRefused(ICAL_TOO_MANY_LINES)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise IcalRefused(ICAL_NOT_UTF8) from None
    try:
        calendars = icalendar.Calendar.from_ical(text, multiple=True)
    except (ValueError, KeyError, IndexError, TypeError):
        raise IcalRefused(ICAL_INVALID) from None
    if not calendars:
        raise IcalRefused(ICAL_INVALID)
    result = IcalResult()
    for calendar in calendars:
        for event in calendar.walk("VEVENT"):
            if isinstance(event, icalendar.Event):
                _read_event(event, result)
    return result


def _dates(event: icalendar.Event) -> tuple[date, date] | IcalSkip:
    """The first and last day an event covers, or why it has none."""
    try:
        start_prop, end_prop = event.get("DTSTART"), event.get("DTEND")
        start_value = start_prop.dt if start_prop is not None else None
        end_value = end_prop.dt if end_prop is not None else None
    except (ValueError, AttributeError):
        start_value = end_value = None
    starts_on = _day(start_value)
    if starts_on is None:
        return IcalSkip.NO_DATE
    if end_value is None:
        ends_on = starts_on
    elif isinstance(end_value, datetime):
        # A timed end exactly at midnight still belongs to the day before.
        ends_on = max(starts_on, (end_value - timedelta(microseconds=1)).date())
    else:
        end_day = _day(end_value) or starts_on
        if end_day < starts_on:
            return IcalSkip.BAD_RANGE
        # All-day ends are exclusive; an end equal to the start (some exports) is one day.
        ends_on = max(starts_on, end_day - timedelta(days=1))
    if ends_on < starts_on:
        return IcalSkip.BAD_RANGE
    if (ends_on - starts_on).days >= MAX_DAYS:
        return IcalSkip.TOO_LONG
    return starts_on, ends_on


def _read_event(event: icalendar.Event, result: IcalResult) -> None:
    name = _name(event)
    if len(result.holidays) >= MAX_EVENTS:
        result.skipped.append(SkippedEvent(name, IcalSkip.TOO_MANY))
        return
    if "RRULE" in event or "RDATE" in event:
        result.skipped.append(SkippedEvent(name, IcalSkip.REPEATING))
        return
    if name is None:
        result.skipped.append(SkippedEvent(None, IcalSkip.NO_NAME))
        return
    dates = _dates(event)
    if isinstance(dates, IcalSkip):
        result.skipped.append(SkippedEvent(name, dates))
        return
    result.holidays.append(ImportedHoliday(name, *dates))
