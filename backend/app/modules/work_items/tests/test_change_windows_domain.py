"""Freeze and maintenance windows and a change's conflicts (WP-045c; ADR-042). No I/O."""

import uuid
from datetime import UTC, datetime, timedelta

from app.modules.work_items.domain.change_windows import (
    ConflictKind,
    Planned,
    Scope,
    Window,
    WindowKind,
    WindowMode,
    conflicts,
    window_problems,
)

MON = datetime(2026, 11, 16, 0, 0, tzinfo=UTC)  # a Monday
H = timedelta(hours=1)
SITE, OTHER_SITE, GROUP = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def window(
    kind: WindowKind,
    start: datetime,
    end: datetime,
    *,
    mode: WindowMode | None = None,
    scope: Scope | None = None,
    weekly: bool = False,
    until: datetime | None = None,
) -> Window:
    return Window(
        id=uuid.uuid4(),
        kind=kind,
        mode=mode or (WindowMode.BLOCK if kind is WindowKind.FREEZE else WindowMode.WARN),
        starts_at=start,
        ends_at=end,
        scope=scope or Scope(),
        repeat_weekly=weekly,
        repeat_until=until,
    )


def test_a_tenant_wide_freeze_blocks_an_overlapping_change() -> None:
    freeze = window(WindowKind.FREEZE, MON, MON + 48 * H)
    found = conflicts([(MON + 10 * H, MON + 12 * H)], site_id=SITE, group_id=None, windows=[freeze])
    assert [(c.kind, c.blocks, c.window_id) for c in found] == [
        (ConflictKind.FREEZE, True, freeze.id)
    ]
    # Touching its end is not overlapping: the intervals are half-open.
    assert (
        conflicts([(MON + 48 * H, MON + 50 * H)], site_id=SITE, group_id=None, windows=[freeze])
        == []
    )


def test_a_warning_freeze_is_shown_but_does_not_block() -> None:
    freeze = window(WindowKind.FREEZE, MON, MON + 48 * H, mode=WindowMode.WARN)
    [found] = conflicts([(MON, MON + H)], site_id=None, group_id=None, windows=[freeze])
    assert (found.kind, found.blocks) == (ConflictKind.FREEZE, False)


def test_a_scoped_freeze_reaches_only_its_sites_and_groups() -> None:
    by_site = window(WindowKind.FREEZE, MON, MON + 48 * H, scope=Scope(site_ids=frozenset({SITE})))
    by_group = window(
        WindowKind.FREEZE, MON, MON + 48 * H, scope=Scope(group_ids=frozenset({GROUP}))
    )
    times = [(MON + H, MON + 2 * H)]
    assert len(conflicts(times, site_id=SITE, group_id=None, windows=[by_site])) == 1
    assert conflicts(times, site_id=OTHER_SITE, group_id=None, windows=[by_site]) == []
    assert len(conflicts(times, site_id=None, group_id=GROUP, windows=[by_group])) == 1
    # Named only for CIs (the CMDB is not here yet): it reaches no change, never every change.
    by_ci = window(
        WindowKind.FREEZE, MON, MON + 48 * H, scope=Scope(ci_ids=frozenset({uuid.uuid4()}))
    )
    assert conflicts(times, site_id=SITE, group_id=GROUP, windows=[by_ci]) == []


def test_d156_c_a_weekly_window_repeats_and_stops_at_its_end() -> None:
    # Every Saturday 22:00 to Sunday 04:00, until the end of the year.
    sat = MON + timedelta(days=5, hours=22)
    weekly = window(
        WindowKind.MAINTENANCE,
        sat,
        sat + 6 * H,
        weekly=True,
        until=datetime(2026, 12, 31, tzinfo=UTC),
    )
    three_weeks_on = sat + timedelta(weeks=3)
    assert weekly.contains(three_weeks_on + H, three_weeks_on + 3 * H)
    assert not weekly.contains(three_weeks_on - H, three_weeks_on + H)  # starts before it opens
    next_year = sat + timedelta(weeks=8)
    assert not weekly.contains(next_year + H, next_year + 2 * H)


def test_d156_b_outside_every_maintenance_window_is_a_warning() -> None:
    sat = MON + timedelta(days=5, hours=22)
    maintenance = window(WindowKind.MAINTENANCE, sat, sat + 6 * H, weekly=True)
    inside = [(sat + H, sat + 2 * H)]
    outside = [(MON + 10 * H, MON + 11 * H)]
    assert conflicts(inside, site_id=None, group_id=None, windows=[maintenance]) == []
    [found] = conflicts(outside, site_id=None, group_id=None, windows=[maintenance])
    assert (found.kind, found.blocks) == (ConflictKind.OUTSIDE_MAINTENANCE, False)
    # No maintenance window in scope: nothing to be outside of.
    assert conflicts(outside, site_id=None, group_id=None, windows=[]) == []


def test_another_change_at_the_same_site_or_in_the_same_group_overlaps_as_a_warning() -> None:
    me = uuid.uuid4()
    same_site = Planned(uuid.uuid4(), MON + H, MON + 3 * H, SITE, None)
    same_group = Planned(uuid.uuid4(), MON + 2 * H, MON + 4 * H, None, GROUP)
    elsewhere = Planned(uuid.uuid4(), MON + H, MON + 3 * H, OTHER_SITE, None)
    myself = Planned(me, MON, MON + 5 * H, SITE, GROUP)
    found = conflicts(
        [(MON + 2 * H, MON + 3 * H)],
        site_id=SITE,
        group_id=GROUP,
        windows=[],
        others=[same_site, same_group, elsewhere, myself],
        record_id=me,
    )
    assert {(c.kind, c.blocks, c.record_id) for c in found} == {
        (ConflictKind.OVERLAP, False, same_site.record_id),
        (ConflictKind.OVERLAP, False, same_group.record_id),
    }


def test_a_window_checks_its_own_times() -> None:
    assert window_problems(None, None, repeat_weekly=False, repeat_until=None) == [
        ("starts_at", "required"),
        ("ends_at", "required"),
    ]
    assert window_problems(MON, MON, repeat_weekly=False, repeat_until=None) == [
        ("ends_at", "end_before_start")
    ]
    assert window_problems(MON, MON + timedelta(days=8), repeat_weekly=True, repeat_until=None) == [
        ("ends_at", "longer_than_a_week")
    ]
    assert window_problems(MON, MON + H, repeat_weekly=False, repeat_until=MON + 2 * H) == [
        ("repeat_until", "not_allowed")
    ]


# --- monthly windows (D-156) --------------------------------------------------------------------


def test_d156_nth_weekday_finds_the_first_and_the_last() -> None:
    from datetime import date  # noqa: PLC0415 - this block's own

    from app.modules.work_items.domain.change_windows import nth_weekday  # noqa: PLC0415

    assert nth_weekday(2027, 3, 1, 6) == date(2027, 3, 7)  # the first Sunday of March 2027
    assert nth_weekday(2027, 3, 5, 4) == date(2027, 3, 26)  # its last Friday
    assert nth_weekday(2027, 2, 4, 0) == date(2027, 2, 22)  # a fourth Monday always exists


def test_d156_a_first_sunday_window_repeats_monthly_on_local_sundays() -> None:
    from zoneinfo import ZoneInfo  # noqa: PLC0415 - this block's own

    karachi = ZoneInfo("Asia/Karachi")
    first = datetime(2027, 3, 7, 2, 0, tzinfo=karachi).astimezone(UTC)  # 02:00 Sunday local
    window = Window(
        id=uuid.uuid4(),
        kind=WindowKind.MAINTENANCE,
        mode=WindowMode.WARN,
        starts_at=first,
        ends_at=first + timedelta(hours=4),
        monthly=(1, 6),
        zone=karachi,
    )
    found = window.occurrences(first, first + timedelta(days=100))
    local = [b.astimezone(karachi) for b, _ in found]
    assert [(d.month, d.day, d.hour) for d in local] == [(3, 7, 2), (4, 4, 2), (5, 2, 2), (6, 6, 2)]
    assert all(d.weekday() == 6 for d in local)  # Sundays in Karachi, Saturdays in UTC
    assert window.contains(found[1][0] + timedelta(hours=1), found[1][0] + timedelta(hours=2))


def test_d156_a_monthly_window_names_its_week_and_day_and_fits_in_a_month() -> None:
    assert window_problems(
        MON, MON + timedelta(days=30), repeat_weekly=False, repeat_until=None, monthly=(1, 6)
    ) == [("ends_at", "longer_than_a_month")]
    assert window_problems(
        MON, MON + H, repeat_weekly=False, repeat_until=None, monthly=(None, 9)
    ) == [("repeat_week", "required"), ("repeat_weekday", "invalid_choice")]
    assert (
        window_problems(
            MON, MON + H, repeat_weekly=False, repeat_until=MON + 90 * H, monthly=(5, 4)
        )
        == []
    )
