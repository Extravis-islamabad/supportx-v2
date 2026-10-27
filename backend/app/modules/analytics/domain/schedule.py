"""When a scheduled report runs (REQ-RPT-052; D-100 D3: minimal scheduling at MVP).

A schedule runs at a wall-clock time in its own time zone: daily, on chosen weekdays, weekly on
one day, or monthly on a day of the month (1-28, so every month has it), from a start date to an
optional end date. Times are computed on the wall clock and then turned into an instant, so a
07:00 Monday schedule in Asia/Riyadh, or across a daylight-saving change elsewhere, still runs
at 07:00 local time (REQ-RPT-052 AC1). A wall-clock time that does not exist on a spring-forward
day runs at the first moment after the gap.

Pure: no clock is read here; callers pass "now" and "after".
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

MAX_DAYS_AHEAD = 400  # more than a year, so a monthly or yearly gap always finds its next day
FAILURES_BEFORE_PAUSE = 3  # Appendix A: a schedule pauses after 3 failed runs in a row
SUNDAY = 6  # weekday numbers: 0 = Monday ... 6 = Sunday
LAST_SAFE_DAY = 28  # the last day every month has


class Frequency(StrEnum):
    """How often a schedule runs."""

    DAILY = "daily"  # every day, or only on `weekdays` when given
    WEEKLY = "weekly"  # on `weekdays[0]` every week
    MONTHLY = "monthly"  # on `day_of_month` every month


@dataclass(frozen=True)
class Recurrence:
    """A schedule's timing, as stored."""

    frequency: Frequency
    at: time  # wall-clock time in `zone`
    zone: str  # IANA name
    start: date
    end: date | None = None
    weekdays: tuple[int, ...] = field(default=())  # 0 = Monday ... 6 = Sunday
    day_of_month: int | None = None  # MONTHLY: 1-28

    def problems(self) -> list[tuple[str, str]]:
        """(field, code) for each rule broken; empty when the recurrence is valid."""
        found: list[tuple[str, str]] = []
        try:
            ZoneInfo(self.zone)
        except (KeyError, ValueError):
            found.append(("time_zone", "invalid_choice"))
        if any(d < 0 or d > SUNDAY for d in self.weekdays) or len(set(self.weekdays)) != len(
            self.weekdays
        ):
            found.append(("weekdays", "invalid_choice"))
        if self.frequency == Frequency.WEEKLY and len(self.weekdays) != 1:
            found.append(("weekdays", "one_day_required"))
        if self.frequency == Frequency.MONTHLY and not (
            self.day_of_month is not None and 1 <= self.day_of_month <= LAST_SAFE_DAY
        ):
            found.append(("day_of_month", "out_of_range"))
        if self.end is not None and self.end < self.start:
            found.append(("end_date", "end_before_start"))
        return found

    def _runs_on(self, day: date) -> bool:
        if day < self.start or (self.end is not None and day > self.end):
            return False
        match self.frequency:
            case Frequency.DAILY:
                return not self.weekdays or day.weekday() in self.weekdays
            case Frequency.WEEKLY:
                return day.weekday() == self.weekdays[0]
            case Frequency.MONTHLY:
                return day.day == self.day_of_month

    def _instant(self, day: date) -> datetime:
        zone = ZoneInfo(self.zone)
        local = datetime.combine(day, self.at, tzinfo=zone)
        # A time inside a spring-forward gap does not exist: run at the first moment after it.
        round_trip = local.astimezone(UTC).astimezone(zone)
        if round_trip.replace(tzinfo=None) != local.replace(tzinfo=None):
            local = round_trip
        return local.astimezone(UTC)

    def next_after(self, after: datetime) -> datetime | None:
        """The first run strictly after `after`, or None when the schedule has ended."""
        zone = ZoneInfo(self.zone)
        day = max(after.astimezone(zone).date(), self.start)
        for _ in range(MAX_DAYS_AHEAD):
            if self.end is not None and day > self.end:
                return None
            if self._runs_on(day):
                instant = self._instant(day)
                if instant > after:
                    return instant
            day += timedelta(days=1)
        return None
