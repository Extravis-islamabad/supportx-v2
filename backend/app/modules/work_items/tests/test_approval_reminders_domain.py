"""Request approval reminders and escalation (WP-047a S3a; REQ-SR-034, -036 AC2): pure, no I/O."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.modules.work_items.domain.approval_reminders import (
    LOOK_BACK,
    Schedule,
    Slot,
    Step,
    due_now,
    family_states,
    plan,
    schedule_problems,
)
from app.modules.work_items.domain.approvals import ApprovalState, LevelRule, level_outcome

KARACHI = ZoneInfo("Asia/Karachi")
DUBAI = ZoneInfo("Asia/Dubai")


def weekdays(day: date) -> bool:
    return day.weekday() < 5


def _local(slot: Slot, zone: ZoneInfo) -> tuple[str, time]:
    at = slot.due.astimezone(zone)
    return at.strftime("%a %d"), at.time()


def test_ac1_sent_monday_morning_the_first_reminder_is_wednesday_at_ten() -> None:
    monday = datetime(2026, 11, 23, 9, 0, tzinfo=KARACHI)  # a Monday
    slots = plan(monday, Schedule(), KARACHI, weekdays)
    assert [(s.step, s.number) for s in slots] == [
        (Step.REMIND, 1),
        (Step.REMIND, 2),
        (Step.REMIND, 3),
        (Step.ESCALATE, 1),
    ]
    assert [_local(s, KARACHI) for s in slots] == [
        ("Wed 25", time(10)),
        ("Thu 26", time(10)),
        ("Fri 27", time(10)),
        ("Mon 30", time(10)),  # the weekend skipped
    ]


def test_ten_oclock_is_in_the_approvers_time_zone() -> None:
    monday = datetime(2026, 11, 23, 4, 0, tzinfo=UTC)
    [first, *_] = plan(monday, Schedule(), DUBAI, weekdays)
    assert first.due.astimezone(DUBAI).time() == time(10)
    assert first.due == datetime(2026, 11, 25, 6, 0, tzinfo=UTC)


def test_a_holiday_is_skipped() -> None:
    holiday = date(2026, 11, 25)
    monday = datetime(2026, 11, 23, 9, 0, tzinfo=KARACHI)
    [first, *_] = plan(monday, Schedule(), KARACHI, lambda d: weekdays(d) and d != holiday)
    assert _local(first, KARACHI) == ("Thu 26", time(10))


def test_a_clarification_pushes_the_plan_back() -> None:
    monday = datetime(2026, 11, 23, 9, 0, tzinfo=KARACHI)
    [first, *_] = plan(monday, Schedule(), KARACHI, weekdays, paused=timedelta(days=1))
    assert _local(first, KARACHI) == ("Thu 26", time(10))


def test_no_escalation_when_the_stage_says_none_and_zero_reminders_escalate_at_once() -> None:
    monday = datetime(2026, 11, 23, 9, 0, tzinfo=KARACHI)
    assert [s.step for s in plan(monday, Schedule(), KARACHI, weekdays, escalates=False)] == [
        Step.REMIND
    ] * 3
    [only] = plan(monday, Schedule(count=0), KARACHI, weekdays)
    assert (only.step, _local(only, KARACHI)) == (Step.ESCALATE, ("Wed 25", time(10)))


def test_a_calendar_with_no_working_day_has_no_slots() -> None:
    monday = datetime(2026, 11, 23, 9, 0, tzinfo=KARACHI)
    assert plan(monday, Schedule(), KARACHI, lambda _d: False) == []


def test_due_now_sends_the_latest_slot_once_and_never_a_burst() -> None:
    monday = datetime(2026, 11, 23, 9, 0, tzinfo=KARACHI)
    slots = plan(monday, Schedule(), KARACHI, weekdays)
    assert due_now(slots, slots[0].due - timedelta(minutes=1)) is None
    assert due_now(slots, slots[0].due) == slots[0]
    assert due_now(slots, slots[2].due + timedelta(hours=1)) == slots[2]  # not 1 and 2 as well


def test_a_missed_reminder_expires_but_a_due_escalation_never_does() -> None:
    monday = datetime(2026, 11, 23, 9, 0, tzinfo=KARACHI)
    reminders_only = plan(monday, Schedule(), KARACHI, weekdays, escalates=False)
    late = reminders_only[-1].due + LOOK_BACK + timedelta(minutes=1)
    assert due_now(reminders_only, late) is None
    slots = plan(monday, Schedule(), KARACHI, weekdays)
    assert due_now(slots, slots[-1].due + timedelta(days=30)) == slots[-1]


def test_schedule_limits() -> None:
    assert schedule_problems(2, 3) == []
    assert schedule_problems(0, 11) == [
        ("approval_reminder_after_days", "out_of_range"),
        ("approval_reminder_count", "out_of_range"),
    ]


@dataclass(frozen=True)
class Row:
    id: uuid.UUID
    state: str
    escalated_from_id: uuid.UUID | None = None


P1, P2, E1, E2 = (uuid.UUID(f"01900000-0000-7000-8000-0000000000a{n}") for n in range(4))


def test_ac2_036_an_escalation_adds_no_vote_under_all() -> None:
    """036 AC2: the primary stays open next to its escalation; together they are one vote."""
    rows = [
        Row(P1, "approved"),
        Row(P2, "pending"),
        Row(E1, "pending", escalated_from_id=P2),
    ]
    assert level_outcome(LevelRule.ALL, family_states(rows)).value == "pending"
    assert family_states(rows) == [ApprovalState.APPROVED, ApprovalState.PENDING]
    decided = [Row(P1, "approved"), Row(P2, "not_needed"), Row(E1, "approved", P2)]
    assert family_states(decided) == [ApprovalState.APPROVED, ApprovalState.APPROVED]
    assert level_outcome(LevelRule.ALL, family_states(decided)).value == "approved"


def test_a_majority_counts_families_not_rows() -> None:
    rows = [
        Row(P1, "approved"),
        Row(P2, "pending"),
        Row(E1, "pending", escalated_from_id=P2),
        Row(E2, "pending", escalated_from_id=P2),  # a group: several escalated rows
    ]
    assert len(family_states(rows)) == 2
    withdrawn = [Row(P1, "withdrawn"), Row(E1, "not_needed", escalated_from_id=P1)]
    assert family_states(withdrawn) == [ApprovalState.WITHDRAWN]


def test_the_snapshot_keeps_escalate_to_and_leaves_the_default_out() -> None:
    from app.modules.work_items.domain import stage_snapshot as snap  # noqa: PLC0415 - one test

    stages = (
        snap.SnapStage(approvers=(snap.SnapApprover("person", P1),)),
        snap.SnapStage(approvers=(snap.SnapApprover("person", P2),), escalate_to="none"),
    )
    stored = snap.to_json(stages)
    assert "escalate_to" not in stored["stages"][0]  # the backup, left out
    assert stored["stages"][1]["escalate_to"] == "none"
    assert snap.from_json(stored) == stages
    wrong = {"v": 1, "stages": [{"approvers": [], "escalate_to": "someone"}]}
    assert snap.problems(wrong) == ["stages.0.escalate_to"]
    # An erased backup keeps the stage's other settings (dataclasses.replace).
    kept = snap.without_person(stages, P1)
    assert kept[1].escalate_to == "none"
