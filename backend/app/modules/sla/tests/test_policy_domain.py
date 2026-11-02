"""SLA policies and the clock, without I/O (WP-025 session 2). Names cite parity file 03."""

import uuid
from datetime import UTC, datetime, timedelta

from app.modules.sla.domain.calendar import Calendar
from app.modules.sla.domain.policy import (
    CalendarSource,
    MetHow,
    PolicyRule,
    PriorityRule,
    ReopenRule,
    TargetKind,
    TargetRow,
    TargetState,
    TargetUnit,
    match,
    meet,
    never_matching,
    overdue,
    pause,
    reopen,
    resume,
    retarget,
    set_by_hand,
    start,
    stop,
    target_problems,
    target_seconds,
    targets_for,
)
from app.modules.sla.domain.setup import WeekPreset, build_calendar, preset_week

UTC_MF = build_calendar(
    kind="hours", time_zone="UTC", week=preset_week(WeekPreset.MON_FRI), holidays=[]
)  # Monday-Friday 09:00-18:00 UTC
AROUND = Calendar.around_the_clock()
MONDAY_10 = datetime(2026, 11, 2, 10, tzinfo=UTC)
HOUR = 3600


def _policy(
    position: int, *, enabled: bool = True, fallback: bool = False, when: bool | None = True
) -> PolicyRule:
    return PolicyRule(
        id=uuid.uuid4(),
        position=position,
        enabled=enabled,
        fallback=fallback,
        has_conditions=when is not None,
        matches=lambda _record: True if when is None else when,
    )


# --- matching (REQ-SLA-001..004) ----------------------------------------------------------------


def test_req_sla_001_first_enabled_match_in_order_wins() -> None:
    first, second = _policy(2), _policy(1)
    assert match([first, second], {}) == second


def test_req_sla_001_disabled_and_unmatched_policies_fall_through_to_the_fallback() -> None:
    fallback = _policy(99, fallback=True, when=None)
    assert match([_policy(1, enabled=False), _policy(2, when=False), fallback], {}) == fallback


def test_req_sla_001_the_fallback_never_wins_over_a_match() -> None:
    hit = _policy(5)
    fallback = _policy(0, fallback=True, when=None)  # its position does not matter
    assert match([fallback, hit], {}) == hit


def test_req_sla_001_policies_below_a_catch_all_can_never_match() -> None:
    catch_all = _policy(1, when=None)
    below = _policy(2)
    disabled_below = _policy(3, enabled=False)
    assert never_matching([below, catch_all, disabled_below]) == [below.id]
    assert never_matching([_policy(1), _policy(2)]) == []


# --- targets ----------------------------------------------------------------------------------


def test_a_priority_row_wins_over_the_all_priorities_row_and_untracked_is_dropped() -> None:
    rows = [
        TargetRow(TargetKind.RESOLUTION, None, 8, TargetUnit.HOURS),
        TargetRow(
            TargetKind.RESOLUTION, "p1", 4, TargetUnit.HOURS, CalendarSource.AROUND_THE_CLOCK
        ),
        TargetRow(TargetKind.FIRST_RESPONSE, "p1", None, TargetUnit.MINUTES),
    ]
    p1 = targets_for(rows, "p1")
    assert p1[TargetKind.RESOLUTION].amount == 4
    assert TargetKind.FIRST_RESPONSE not in p1  # "not tracked"
    assert targets_for(rows, "p3")[TargetKind.RESOLUTION].amount == 8


def test_a_business_day_is_one_working_day_of_the_calendar() -> None:
    three_days = TargetRow(TargetKind.RESOLUTION, "p3", 3, TargetUnit.BUSINESS_DAYS)
    assert target_seconds(three_days, UTC_MF) == 3 * 9 * HOUR
    assert target_seconds(three_days, AROUND) == 3 * 24 * HOUR
    assert (
        target_seconds(TargetRow(TargetKind.FIRST_RESPONSE, None, 15, TargetUnit.MINUTES), AROUND)
        == 900
    )


def test_target_rows_an_admin_cannot_save() -> None:
    rows = [
        TargetRow(TargetKind.RESOLUTION, "p1", 4, TargetUnit.HOURS),
        TargetRow(TargetKind.RESOLUTION, "p1", 5, TargetUnit.HOURS),
        TargetRow(TargetKind.RESOLUTION, "p2", 0, TargetUnit.HOURS),
        TargetRow(TargetKind.RESOLUTION, "p3", 1, TargetUnit.HOURS, CalendarSource.FIXED),
        TargetRow(
            TargetKind.RESOLUTION, "p4", 1, TargetUnit.HOURS, CalendarSource.SITE, uuid.uuid4()
        ),
    ]
    assert target_problems(rows) == [
        (1, "target_duplicate"),
        (2, "target_amount_invalid"),
        (3, "fixed_calendar_required"),
        (4, "fixed_calendar_unused"),
    ]


# --- the clock (REQ-SLA-015, 016, 018, 020, 027, 028, 029) -------------------------------------


def test_a_running_clock_is_due_after_its_business_time() -> None:
    clock = start(TargetKind.RESOLUTION, 8 * HOUR, MONDAY_10, UTC_MF)
    # 8 business hours from Mon 10:00 end exactly at Monday's close, not Tuesday's opening.
    assert clock.due_at == datetime(2026, 11, 2, 18, tzinfo=UTC)


def test_req_sla_015_ac1_a_one_hour_business_pause_moves_the_due_date_one_business_hour() -> None:
    clock = start(TargetKind.RESOLUTION, 4 * HOUR, MONDAY_10, UTC_MF)
    assert clock.due_at == datetime(2026, 11, 2, 14, tzinfo=UTC)
    paused = pause(clock, MONDAY_10 + timedelta(hours=1), UTC_MF)
    assert (paused.state, paused.due_at, paused.used) == (TargetState.PAUSED, None, HOUR)
    resumed = resume(paused, MONDAY_10 + timedelta(hours=2), UTC_MF)
    assert resumed.due_at == datetime(2026, 11, 2, 15, tzinfo=UTC)
    assert resumed.paused_seconds == HOUR


def test_req_sla_015_ac2_a_pause_entirely_outside_business_hours_changes_nothing() -> None:
    evening = datetime(2026, 11, 2, 18, tzinfo=UTC)
    long = start(TargetKind.RESOLUTION, 20 * HOUR, MONDAY_10, UTC_MF)
    paused = pause(long, evening, UTC_MF)
    resumed = resume(paused, datetime(2026, 11, 3, 8, tzinfo=UTC), UTC_MF)
    assert resumed.due_at == long.due_at
    assert resumed.paused_seconds == 0


def test_met_on_time_late_and_at_resolution() -> None:
    clock = start(TargetKind.FIRST_RESPONSE, HOUR, MONDAY_10, UTC_MF)
    on_time = meet(clock, MONDAY_10 + timedelta(minutes=30), UTC_MF)
    assert (on_time.state, on_time.met_how) == (TargetState.MET, MetHow.ON_TIME)
    late = meet(clock, MONDAY_10 + timedelta(hours=2), UTC_MF)
    assert late.met_how is MetHow.LATE
    by_resolution = meet(clock, MONDAY_10 + timedelta(minutes=5), UTC_MF, how=MetHow.AT_RESOLUTION)
    assert by_resolution.met_how is MetHow.AT_RESOLUTION  # D-115 D8
    # Met stamps never change (REQ-SLA-020).
    assert meet(on_time, MONDAY_10 + timedelta(hours=3), UTC_MF) == on_time


def test_closing_or_canceling_stops_an_open_clock_without_a_breach() -> None:
    clock = start(TargetKind.RESOLUTION, HOUR, MONDAY_10, UTC_MF)
    stopped = stop(clock, MONDAY_10 + timedelta(hours=5), UTC_MF)
    assert stopped.state is TargetState.STOPPED
    assert stopped.breached_at is None


def test_req_sla_029_reopen_resumes_from_used_time_or_restarts_a_round() -> None:
    clock = start(TargetKind.RESOLUTION, 4 * HOUR, MONDAY_10, UTC_MF)
    resolved = meet(clock, MONDAY_10 + timedelta(hours=3), UTC_MF)
    assert resolved.used == 3 * HOUR
    reopened_at = datetime(2026, 11, 3, 10, tzinfo=UTC)  # a business day later
    resumed = reopen(resolved, reopened_at, UTC_MF, ReopenRule.RESUME, 4 * HOUR)
    # Time spent resolved never counted: one business hour left.
    assert resumed.due_at == reopened_at + timedelta(hours=1)
    assert resumed.state is TargetState.RUNNING
    restarted = reopen(resolved, reopened_at, UTC_MF, ReopenRule.RESTART, 4 * HOUR)
    assert restarted.due_at == reopened_at + timedelta(hours=4)
    assert restarted.used == 0


def test_req_sla_027_a_raised_priority_recalculates_from_the_sla_start() -> None:
    p3 = start(TargetKind.RESOLUTION, 27 * HOUR, MONDAY_10, UTC_MF)
    later = MONDAY_10 + timedelta(hours=5)
    paused = pause(p3, later, UTC_MF)  # count the five hours (recalculation uses `used`)
    p1 = retarget(paused, 4 * HOUR, later, UTC_MF, PriorityRule.RECALCULATE, MONDAY_10)
    running = resume(p1, later, UTC_MF)
    # 5 hours already used of a 4-hour target: due at once, which the caller marks breached.
    assert running.due_at == later
    assert overdue(running, later)


def test_req_sla_027_restart_gives_the_full_new_target_from_the_change() -> None:
    clock = start(TargetKind.RESOLUTION, 27 * HOUR, MONDAY_10, UTC_MF)
    change = MONDAY_10 + timedelta(hours=2)
    restarted = retarget(clock, 4 * HOUR, change, UTC_MF, PriorityRule.RESTART, MONDAY_10)
    assert restarted.due_at == change + timedelta(hours=4)


def test_req_sla_028_a_due_date_set_by_hand_wins_until_cleared() -> None:
    clock = start(TargetKind.RESOLUTION, 4 * HOUR, MONDAY_10, UTC_MF)
    friday = datetime(2026, 11, 6, 17, tzinfo=UTC)
    manual = set_by_hand(clock, friday, UTC_MF)
    assert manual.due_at == friday
    # A recalculation keeps it.
    assert (
        retarget(manual, HOUR, MONDAY_10, UTC_MF, PriorityRule.RECALCULATE, MONDAY_10).due_at
        == friday
    )
    cleared = set_by_hand(manual, None, UTC_MF)
    assert cleared.due_at == clock.due_at


def test_around_the_clock_counts_nights_and_weekends() -> None:
    saturday = datetime(2026, 11, 7, 22, tzinfo=UTC)
    clock = start(TargetKind.RESOLUTION, 4 * HOUR, saturday, AROUND)
    assert clock.due_at == saturday + timedelta(hours=4)
