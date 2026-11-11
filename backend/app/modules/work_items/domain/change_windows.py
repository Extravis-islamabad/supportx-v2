"""Freeze and maintenance windows, and a change's conflicts with them (WP-045c; ADR-042). Pure.

A window is a time a tenant says changes must not happen (a freeze) or should happen (a
maintenance window), for the whole tenant or for some sites, groups, services or CIs (the
latter two kept until the CMDB serves them). It repeats weekly, monthly on the Nth weekday ("first
Sunday", "last Friday"; D-156, Haider 2026-11-11) or not at all.

A change's planned time (its implementation window and its planned downtimes) conflicts:

* with a **freeze** it overlaps, in scope: the freeze's mode decides (block or warn; a new
  freeze blocks, D-156 (a));
* with **maintenance windows**: when any is in scope and the time is not wholly inside one
  occurrence, a warning by default (D-156 (b)), or a block if the window says so;
* with **another open change** in the same group or at the same site at the same time: a
  warning, never a block (the two may be planned together on purpose).

Each conflict says which window or change and why, so the screen can say it plainly.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo
from enum import StrEnum

WEEK = timedelta(days=7)
MAX_OCCURRENCES = 520  # ten years of a weekly window: never an endless loop
MONTH_SPAN = timedelta(days=28)  # a monthly window is at most this long (the shortest month)
LAST = 5  # a monthly window's `week` 5: the month's last such weekday
DECEMBER = 12


def nth_weekday(year: int, month: int, week: int, weekday: int) -> date | None:
    """The `week`-th `weekday` (0 Monday) of a month, or its last for week 5; None if none."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    if week == LAST:
        nxt = date(year + month // 12, month % 12 + 1, 1)
        last_day = nxt - timedelta(days=1)
        return last_day - timedelta(days=(last_day.weekday() - weekday) % 7)
    day = first + timedelta(days=offset + 7 * (week - 1))
    return day if day.month == month else None


class WindowKind(StrEnum):
    """What a window says about changes (REQ-CHG-075, -076)."""

    FREEZE = "freeze"  # no changes then
    MAINTENANCE = "maintenance"  # changes belong then


class WindowMode(StrEnum):
    """What a conflict with the window does to a save (REQ-CHG-077)."""

    BLOCK = "block"  # refused unless someone with the override says why
    WARN = "warn"  # saved, and the conflict is shown


class ConflictKind(StrEnum):
    """Why a change's time conflicts (labels `change_conflict.*`)."""

    FREEZE = "freeze"
    OUTSIDE_MAINTENANCE = "outside_maintenance"
    OVERLAP = "overlap"


KIND_DEFAULT_MODE = {WindowKind.FREEZE: WindowMode.BLOCK, WindowKind.MAINTENANCE: WindowMode.WARN}


@dataclass(frozen=True)
class Scope:
    """Where a window applies; all empty: the whole tenant."""

    site_ids: frozenset[uuid.UUID] = frozenset()
    group_ids: frozenset[uuid.UUID] = frozenset()
    service_ids: frozenset[uuid.UUID] = frozenset()
    ci_ids: frozenset[uuid.UUID] = frozenset()

    @property
    def tenant_wide(self) -> bool:
        """Nothing named: every change."""
        return not (self.site_ids or self.group_ids or self.service_ids or self.ci_ids)

    def covers(self, site_id: uuid.UUID | None, group_id: uuid.UUID | None) -> bool:
        """Whether a change at this site, in this group, is in the window's scope.

        Services and CIs come with the CMDB; until then a window named only for them reaches
        no change (it is never silently tenant-wide).
        """
        if self.tenant_wide:
            return True
        return (site_id is not None and site_id in self.site_ids) or (
            group_id is not None and group_id in self.group_ids
        )


@dataclass(frozen=True)
class Window:
    """A freeze or maintenance window, as stored."""

    id: uuid.UUID
    kind: WindowKind
    mode: WindowMode
    starts_at: datetime
    ends_at: datetime
    scope: Scope = field(default_factory=Scope)
    repeat_weekly: bool = False
    repeat_until: datetime | None = None
    # A monthly window (D-156): (week 1..4 or 5 for the last, weekday 0 Monday .. 6 Sunday), on
    # the local date and time of its first occurrence in `zone` (the tenant's), so "first
    # Sunday at 02:00" stays a Sunday wherever UTC falls.
    monthly: tuple[int, int] | None = None
    zone: tzinfo = UTC

    def _monthly(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        assert self.monthly is not None  # noqa: S101 - only called for monthly windows
        week, weekday = self.monthly
        length = self.ends_at - self.starts_at
        local = self.starts_at.astimezone(self.zone)
        # Begin with the month before `start` (an occurrence may run into it), never before
        # the first one.
        begin_from = max(start - MONTH_SPAN, self.starts_at).astimezone(self.zone)
        year, month = begin_from.year, begin_from.month
        found: list[tuple[datetime, datetime]] = []
        for _ in range(MAX_OCCURRENCES):
            day = nth_weekday(year, month, week, weekday)
            if day is not None:
                begin = (
                    datetime.combine(day, local.timetz().replace(tzinfo=None))
                    .replace(tzinfo=self.zone)
                    .astimezone(UTC)
                )
                if begin >= end or (self.repeat_until is not None and begin > self.repeat_until):
                    break
                finish = begin + length
                if begin >= self.starts_at and overlaps(begin, finish, start, end):
                    found.append((begin, finish))
            year, month = (year + 1, 1) if month == DECEMBER else (year, month + 1)
        return found

    def occurrences(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        """The window's occurrences that touch [start, end), in order."""
        if self.monthly is not None:
            return self._monthly(start, end)
        if not self.repeat_weekly:
            return (
                [(self.starts_at, self.ends_at)]
                if overlaps(self.starts_at, self.ends_at, start, end)
                else []
            )
        length = self.ends_at - self.starts_at
        # Skip whole weeks before `start` instead of walking them.
        skip = max(0, (start - self.ends_at) // WEEK) if start > self.ends_at else 0
        found: list[tuple[datetime, datetime]] = []
        for k in range(skip, skip + MAX_OCCURRENCES):
            begin = self.starts_at + k * WEEK
            if begin >= end or (self.repeat_until is not None and begin > self.repeat_until):
                break
            finish = begin + length
            if overlaps(begin, finish, start, end):
                found.append((begin, finish))
        return found

    def contains(self, start: datetime, end: datetime) -> bool:
        """Whether one occurrence holds the whole of [start, end)."""
        return any(b <= start and end <= f for b, f in self.occurrences(start, end))


@dataclass(frozen=True)
class Planned:
    """Another change's planned time, for the overlap check."""

    record_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    site_id: uuid.UUID | None
    group_id: uuid.UUID | None


@dataclass(frozen=True)
class Conflict:
    """One conflict and whether it blocks the save."""

    kind: ConflictKind
    starts_at: datetime
    ends_at: datetime
    blocks: bool
    window_id: uuid.UUID | None = None
    record_id: uuid.UUID | None = None


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Half-open intervals touch: [a_start, a_end) and [b_start, b_end) share a moment."""
    return a_start < b_end and b_start < a_end


def conflicts(  # noqa: PLR0913 - the change's times, place and the world it meets, explicit
    times: Sequence[tuple[datetime, datetime]],
    *,
    site_id: uuid.UUID | None,
    group_id: uuid.UUID | None,
    windows: Iterable[Window],
    others: Iterable[Planned] = (),
    record_id: uuid.UUID | None = None,
    outside_blocks: bool = False,
) -> list[Conflict]:
    """Every conflict of the change's planned times, in time order (none for no times).

    `outside_blocks`: the tenant's setting that being outside every maintenance window blocks,
    whatever the windows' own mode (D-156; off: each window's mode decides, warn by default).
    """
    found: list[Conflict] = []
    in_scope = [w for w in windows if w.scope.covers(site_id, group_id)]
    freezes = [w for w in in_scope if w.kind is WindowKind.FREEZE]
    maintenance = [w for w in in_scope if w.kind is WindowKind.MAINTENANCE]
    for start, end in times:
        found.extend(
            Conflict(ConflictKind.FREEZE, start, end, w.mode is WindowMode.BLOCK, w.id)
            for w in freezes
            if w.occurrences(start, end)
        )
        if maintenance and not any(w.contains(start, end) for w in maintenance):
            blocks = outside_blocks or any(w.mode is WindowMode.BLOCK for w in maintenance)
            found.append(Conflict(ConflictKind.OUTSIDE_MAINTENANCE, start, end, blocks))
        for o in others:
            if o.record_id == record_id or not overlaps(start, end, o.starts_at, o.ends_at):
                continue
            same_group = group_id is not None and o.group_id == group_id
            same_site = site_id is not None and o.site_id == site_id
            if same_group or same_site:
                found.append(
                    Conflict(ConflictKind.OVERLAP, start, end, blocks=False, record_id=o.record_id)
                )
    return sorted(found, key=lambda c: (c.starts_at, c.kind.value))


def window_problems(
    starts_at: datetime | None,
    ends_at: datetime | None,
    *,
    repeat_weekly: bool,
    repeat_until: datetime | None,
    monthly: tuple[int | None, int | None] | None = None,
) -> list[tuple[str, str]]:
    """A window's own checks (field, code); labels `errors.field.*`."""
    problems = [
        (n, "required") for n, v in (("starts_at", starts_at), ("ends_at", ends_at)) if v is None
    ]
    if starts_at is not None and ends_at is not None:
        if ends_at <= starts_at:
            problems.append(("ends_at", "end_before_start"))
        elif repeat_weekly and ends_at - starts_at > WEEK:
            problems.append(("ends_at", "longer_than_a_week"))
        elif monthly is not None and ends_at - starts_at > MONTH_SPAN:
            problems.append(("ends_at", "longer_than_a_month"))
    if monthly is not None:
        week, weekday = monthly
        if week is None or not 1 <= week <= LAST:
            problems.append(("repeat_week", "required" if week is None else "invalid_choice"))
        if weekday is None or not 0 <= weekday <= 6:  # noqa: PLR2004 - Monday .. Sunday
            problems.append(("repeat_weekday", "required" if weekday is None else "invalid_choice"))
    if repeat_until is not None and not repeat_weekly and monthly is None:
        problems.append(("repeat_until", "not_allowed"))
    if repeat_until is not None and starts_at is not None and repeat_until < starts_at:
        problems.append(("repeat_until", "end_before_start"))
    return problems
