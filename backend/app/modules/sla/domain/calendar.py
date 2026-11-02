"""Business time: the one calendar service for all SLA date maths (REQ-SLA-014, WP-025).

Pure Python, no I/O. Every due date, elapsed time, paused time and report figure is worked out
here, so the countdown, the list and the history agree to the second (REQ-SLA-014 AC2).

How it works (wp-025-plan.md §3.3):

- A calendar is a working week in one IANA time zone: periods per weekday in local wall-clock
  time, plus holidays. A period whose end is not after its start crosses midnight
  (22:00-06:00 is one period, REQ-SLA-014 AC3); it belongs to the day it starts on.
- Each local period is turned into a UTC interval **on its own date**, so daylight saving is
  right on the day it changes: a night shift over a spring-forward change is an hour shorter.
  A local time inside a spring-forward gap takes the offset from before the change (02:30
  becomes 03:30); an ambiguous autumn time is read as its first occurrence (`fold=0`).
- A holiday removes the periods that **start** on its date. A half day removes the morning or the
  afternoon: the day's working time is split at its half (by working minutes, not by the clock),
  so 09:00-18:00 splits at 13:30 and 08:00-12:00 + 13:00-17:00 at 12:00 / 13:00.
- "Around the clock" counts every second.

All instants in and out are timezone-aware; results are UTC.
"""

import enum
import itertools
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MINUTES_PER_DAY = 24 * 60
DAYS_PER_WEEK = 7
# The furthest any calculation looks (ten years): a calendar with almost no working time cannot
# loop for ever, and a target that does not fit is an error, never a silent wrong date.
HORIZON_DAYS = 3660
MAX_RANGE_DAYS = 366  # a date range of special hours is at most a year
_ONE_SECOND = timedelta(seconds=1)
NO_WORKING_TIME = "no_working_time"


class CalendarKind(enum.StrEnum):
    """What a calendar counts."""

    HOURS = "hours"  # its working periods only
    AROUND_THE_CLOCK = "around_the_clock"  # every second


class HolidayPart(enum.StrEnum):
    """How much of a working day a holiday takes."""

    FULL = "full"
    MORNING = "morning"  # the first half of the day's working time is off
    AFTERNOON = "afternoon"  # the second half is off


class CalendarError(ValueError):
    """A calendar that cannot answer (no working time within the horizon)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, order=True)
class Period:
    """One working period on one weekday, in local wall-clock minutes.

    `weekday` is 0 (Monday) to 6 (Sunday). `start` is 0..1439. `end` is 1..1440; an `end` that is
    not after `start` crosses midnight and ends on the next day (`end` == `start` is 24 hours).
    """

    weekday: int
    start: int
    end: int

    @property
    def crosses_midnight(self) -> bool:
        """Whether the period ends on the next day."""
        return self.end <= self.start

    @property
    def minutes(self) -> int:
        """Its nominal length in minutes (a daylight-saving day can change the real length)."""
        return (
            self.end - self.start
            if not self.crosses_midnight
            else MINUTES_PER_DAY - self.start + self.end
        )

    def week_span(self) -> tuple[int, int]:
        """Its place in the week as minutes from Monday 00:00 (end may pass the week's end)."""
        begin = self.weekday * MINUTES_PER_DAY + self.start
        return begin, begin + self.minutes


def period_errors(periods: Sequence[Period]) -> list[str]:
    """Codes for a week that cannot be used: bad values or overlapping periods."""
    errors: list[str] = []
    for period in periods:
        if not 0 <= period.weekday < DAYS_PER_WEEK:
            errors.append("period_weekday_invalid")
        if not 0 <= period.start < MINUTES_PER_DAY or not 0 < period.end <= MINUTES_PER_DAY:
            errors.append("period_time_invalid")
    if errors:
        return sorted(set(errors))
    week = DAYS_PER_WEEK * MINUTES_PER_DAY
    spans: list[tuple[int, int]] = []
    for period in periods:
        begin, end = period.week_span()
        spans.append((begin, end))
        if end > week:  # Sunday night into Monday morning: also check it against Monday
            spans.append((begin - week, end - week))
    spans.sort()
    for (_, first_end), (second_begin, _) in itertools.pairwise(spans):
        if second_begin < first_end:
            return ["periods_overlap"]
    return []


def zone_or_none(name: str) -> ZoneInfo | None:
    """The IANA zone, or None when the name is not one (tzdata ships in every image, D-115)."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


@dataclass(frozen=True)
class SpecialHours:
    """Other working hours for a date range (Ramadan 09:00-14:00, with a Friday prayer break).

    (rule: special date-range hours) Inside the range its own week replaces the normal week, so a
    break is the gap between two periods and a weekday without periods is closed. Precedence:
    holiday > special date-range hours > weekly schedule; a half day halves the range's hours.
    The one place this rule lives (`Calendar._week_on`); named cases in the business-time table.
    """

    starts_on: date
    ends_on: date
    periods: tuple[Period, ...] = ()


def special_hours_problems(ranges: Sequence[SpecialHours]) -> list[str]:
    """Codes for date-range hours that cannot be used: bad ranges, weeks, or overlaps."""
    errors: list[str] = []
    for item in ranges:
        if item.ends_on < item.starts_on:
            errors.append("exception_range_order")
        elif (item.ends_on - item.starts_on).days >= MAX_RANGE_DAYS:
            errors.append("exception_range_too_long")
        errors.extend(period_errors(item.periods))
    ordered = sorted(ranges, key=lambda r: r.starts_on)
    if any(b.starts_on <= a.ends_on for a, b in itertools.pairwise(ordered)):
        errors.append("exception_ranges_overlap")
    return sorted(set(errors))


@dataclass(frozen=True)
class Calendar:
    """A working calendar ready for maths: zone, week, date-range hours and holidays."""

    zone: ZoneInfo
    kind: CalendarKind = CalendarKind.HOURS
    periods: tuple[Period, ...] = ()
    holidays: Mapping[date, HolidayPart] = field(default_factory=dict)
    special: tuple[SpecialHours, ...] = ()

    @classmethod
    def around_the_clock(cls) -> "Calendar":
        """Every second counts (the calendar every tenant always has)."""
        return cls(zone=ZoneInfo("UTC"), kind=CalendarKind.AROUND_THE_CLOCK)

    @property
    def counts_everything(self) -> bool:
        """Whether every second is business time."""
        return self.kind is CalendarKind.AROUND_THE_CLOCK

    def _by_weekday(self, periods: Sequence[Period] | None = None) -> dict[int, list[Period]]:
        week: dict[int, list[Period]] = {}
        for period in sorted(self.periods if periods is None else periods):
            week.setdefault(period.weekday, []).append(period)
        return week

    def _week_on(self, day: date, week: Mapping[int, list[Period]]) -> Mapping[int, list[Period]]:
        """(rule: special date-range hours) The range's week on its dates, else the normal one."""
        for item in self.special:
            if item.starts_on <= day <= item.ends_on:
                return self._by_weekday(item.periods)
        return week

    def _local_instant(self, day: date, minute: int) -> datetime:
        """The UTC instant of `minute` past local midnight on `day` (1440 = next midnight)."""
        extra, minute = divmod(minute, MINUTES_PER_DAY)
        wall = datetime.combine(day + timedelta(days=extra), time(minute // 60, minute % 60))
        # (rule: daylight-saving gap) The one place it lives; named cases in the case table.
        # fold=0 (PEP 495): an ambiguous autumn time is its first occurrence, and a time inside a
        # spring-forward gap takes the offset from before the change (02:30 becomes 03:30).
        return wall.replace(tzinfo=self.zone).astimezone(UTC)

    def day_intervals(
        self, day: date, week: Mapping[int, list[Period]] | None = None
    ) -> list[tuple[datetime, datetime]]:
        """The UTC working intervals of the periods that start on local `day`, holidays applied.

        (rule: holiday by start date) A holiday removes the periods that start on its date; the
        one place this rule lives (docs/architecture/sla-business-time.md, named cases).
        """
        week = self._week_on(day, self._by_weekday() if week is None else week)
        part = self.holidays.get(day)
        if part is HolidayPart.FULL:
            return []
        intervals: list[tuple[datetime, datetime]] = []
        for period in week.get(day.weekday(), ()):
            end_minute = period.end + (MINUTES_PER_DAY if period.crosses_midnight else 0)
            start, end = (
                self._local_instant(day, period.start),
                self._local_instant(day, end_minute),
            )
            if end > start:
                intervals.append((start, end))
        if part is None or not intervals:
            return intervals
        return _half(intervals, keep_first=part is HolidayPart.AFTERNOON)

    def intervals(
        self, start: datetime, *, horizon_days: int = HORIZON_DAYS
    ) -> Iterator[tuple[datetime, datetime]]:
        """Working intervals in time order from the one containing or following `start`."""
        week = self._by_weekday()
        if not week and not any(item.periods for item in self.special):
            return
        start = start.astimezone(UTC)  # results are UTC whatever zone the caller used
        # A period from the day before can still be running (it may cross midnight).
        first = start.astimezone(self.zone).date() - timedelta(days=1)
        last_end = start
        for offset in range(horizon_days + 1):
            for opens, end in self.day_intervals(first + timedelta(days=offset), week):
                # A night period of one schedule may run into the next day's other schedule
                # (a range starts or ends): time is counted once, never twice.
                begin = max(opens, last_end)
                if end > begin:
                    yield begin, end
                    last_end = end

    def working_at(self, instant: datetime) -> bool:
        """Whether `instant` is business time."""
        _check_aware(instant)
        if self.counts_everything:
            return True
        for begin, _end in self.intervals(instant, horizon_days=2):
            return begin <= instant
        return False

    def add(self, start: datetime, seconds: int) -> datetime:
        """The instant `seconds` of business time after `start` (UTC).

        Zero returns `start` itself. A result exactly at a period's end stays there, so a
        2-hour target ending at 17:00 is due at 17:00, not at the next morning.
        """
        _check_aware(start)
        if seconds < 0:
            msg = "seconds must not be negative"
            raise ValueError(msg)
        if seconds == 0 or self.counts_everything:
            return (start + timedelta(seconds=seconds)).astimezone(UTC)
        left = timedelta(seconds=seconds)
        for begin, end in self.intervals(start):
            span = end - begin
            if span >= left:
                return begin + left
            left -= span
        raise CalendarError(NO_WORKING_TIME)

    def between(self, a: datetime, b: datetime) -> int:
        """Whole seconds of business time from `a` to `b` (negative when `b` is before `a`)."""
        _check_aware(a)
        _check_aware(b)
        if b < a:
            return -self.between(b, a)
        if self.counts_everything:
            return (b - a) // _ONE_SECOND
        total = timedelta()
        for begin, end in self.intervals(a):
            if begin >= b:
                break
            total += min(end, b) - begin
        return total // _ONE_SECOND

    def day_seconds(self) -> int:
        """Nominal business seconds in one working day (the average over its working days).

        A "business day" target (wp-025-plan.md §2) is this many business seconds; around the
        clock it is 24 hours.
        """
        if self.counts_everything:
            return MINUTES_PER_DAY * 60
        totals: dict[int, int] = {}
        for period in self.periods:
            totals[period.weekday] = totals.get(period.weekday, 0) + period.minutes
        if not totals:
            raise CalendarError(NO_WORKING_TIME)
        return round(sum(totals.values()) / len(totals)) * 60


def _half(
    intervals: list[tuple[datetime, datetime]], *, keep_first: bool
) -> list[tuple[datetime, datetime]]:
    """The first or second half of a day's intervals, split at half of their working time.

    (rule: half day) The one place this rule lives; named cases in the business-time table.
    """
    total = sum((end - begin for begin, end in intervals), timedelta())
    half = total / 2
    first: list[tuple[datetime, datetime]] = []
    second: list[tuple[datetime, datetime]] = []
    used = timedelta()
    for begin, end in intervals:
        span = end - begin
        if used + span <= half:
            first.append((begin, end))
        elif used >= half:
            second.append((begin, end))
        else:
            cut = begin + (half - used)
            first.append((begin, cut))
            second.append((cut, end))
        used += span
    return first if keep_first else second


def _check_aware(instant: datetime) -> None:
    if instant.tzinfo is None or instant.utcoffset() is None:
        msg = "instants must be timezone-aware"
        raise ValueError(msg)


def parse_hhmm(value: str) -> int:
    """Minutes past midnight for "HH:MM" ("24:00" is 1440, a period's end at midnight)."""
    hours, _, minutes = value.partition(":")
    if len(hours) != 2 or len(minutes) != 2 or not (hours + minutes).isdigit():  # noqa: PLR2004 - HH and MM
        raise ValueError(value)
    total = int(hours) * 60 + int(minutes)
    if int(minutes) >= 60 or total > MINUTES_PER_DAY:  # noqa: PLR2004 - minutes per hour
        raise ValueError(value)
    return total


def format_hhmm(minutes: int) -> str:
    """Format minutes past midnight as "HH:MM" (1440 is "24:00")."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"
