"""Where escalation levels fall on a target's business-time line (REQ-SLA-022, 025)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.modules.sla.domain.calendar import Calendar
from app.modules.sla.domain.escalation import (
    Action,
    ActionKind,
    Anchor,
    Level,
    Recipient,
    RecipientKind,
    level_moment,
    level_of,
    level_problems,
)
from app.modules.sla.domain.policy import TargetKind, breach, pause, resume, start

ALL_DAY = Calendar.around_the_clock()
T0 = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
HOUR = 3600
WHO = (Recipient(RecipientKind.ASSIGNEE),)


def _level(offset: int, anchor: Anchor = Anchor.DUE, position: int = 1) -> Level:
    return Level(TargetKind.RESOLUTION, position, anchor, offset, recipients=WHO)


def test_levels_before_at_and_after_the_due_moment() -> None:
    clock = start(TargetKind.RESOLUTION, 4 * HOUR, T0, ALL_DAY)
    assert level_moment(_level(-HOUR), clock, ALL_DAY, 75) == T0 + timedelta(hours=3)
    assert level_moment(_level(0), clock, ALL_DAY, 75) == T0 + timedelta(hours=4)
    assert level_moment(_level(2 * HOUR), clock, ALL_DAY, 75) == T0 + timedelta(hours=6)
    # The warning point counts as a level when the admin wants (75 % of 4 h = 3 h).
    assert level_moment(_level(0, Anchor.WARNING), clock, ALL_DAY, 75) == T0 + timedelta(hours=3)


def test_req_sla_025_ac2_a_pause_holds_a_level_and_the_resume_moves_it() -> None:
    clock = start(TargetKind.RESOLUTION, 4 * HOUR, T0, ALL_DAY)
    paused = pause(clock, T0 + timedelta(hours=1), ALL_DAY)
    assert level_moment(_level(0), paused, ALL_DAY, 75) is None  # held
    resumed = resume(paused, T0 + timedelta(hours=3), ALL_DAY)
    # One hour used before the pause: three left, from the resume.
    assert level_moment(_level(0), resumed, ALL_DAY, 75) == T0 + timedelta(hours=6)


def test_req_sla_025_ac3_a_due_date_set_by_hand_moves_every_level() -> None:
    clock = start(TargetKind.RESOLUTION, 4 * HOUR, T0, ALL_DAY)
    by_hand = replace(clock, manual_due_at=T0 + timedelta(days=1, hours=4))
    assert level_moment(_level(-HOUR), by_hand, ALL_DAY, 75) == T0 + timedelta(days=1, hours=3)
    assert level_moment(_level(2 * HOUR), by_hand, ALL_DAY, 75) == T0 + timedelta(days=1, hours=6)
    assert level_moment(_level(0, Anchor.WARNING), by_hand, ALL_DAY, 75) is None


def test_a_breached_clock_still_runs_its_later_levels_and_a_passed_level_is_due_at_once() -> None:
    clock = start(TargetKind.RESOLUTION, 4 * HOUR, T0, ALL_DAY)
    breached = breach(clock, T0 + timedelta(hours=4))
    assert level_moment(_level(2 * HOUR), breached, ALL_DAY, 75) == T0 + timedelta(hours=6)
    shrunk = start(TargetKind.RESOLUTION, HOUR, T0, ALL_DAY)
    used_more = replace(shrunk, used=2 * HOUR)
    assert level_moment(_level(-30 * 60), used_more, ALL_DAY, 75) == T0  # passed: now


def test_levels_round_trip_through_their_snapshot() -> None:
    level = Level(
        TargetKind.FIRST_RESPONSE,
        2,
        Anchor.DUE,
        -600,
        recipients=(Recipient(RecipientKind.USER, "u-1"),),
        fallback=(Recipient(RecipientKind.GROUP_HEAD),),
        actions=(Action(ActionKind.ADD_NOTE, text="Chase it"),),
    )
    assert level_of(level.as_json()) == level
    assert level.key == "first_response:2"


def test_what_is_wrong_with_levels() -> None:
    def codes(levels: list[Level]) -> set[str]:
        return {code for _field, code, _params in level_problems(levels)}

    assert codes([_level(0)]) == set()
    assert codes([Level(TargetKind.RESOLUTION, 1, Anchor.DUE, 0)]) == {"required"}
    silent = Level(TargetKind.RESOLUTION, 1, Anchor.DUE, 0, notify=False)
    assert codes([silent]) == {"level_does_nothing"}
    assert codes([_level(0), _level(0, position=2)]) == {"levels_same_moment"}
    assert codes([_level(i * 60, position=i + 1) for i in range(9)]) == {"too_many_levels"}
    nameless = Level(
        TargetKind.RESOLUTION, 1, Anchor.DUE, 0, recipients=(Recipient(RecipientKind.USER),)
    )
    assert codes([nameless]) == {"recipient_shape"}
    move = Level(
        TargetKind.RESOLUTION,
        1,
        Anchor.DUE,
        0,
        notify=False,
        actions=(Action(ActionKind.REASSIGN_GROUP),),
    )
    assert codes([move]) == {"required"}
    assert codes([_level(31 * 24 * HOUR)]) == {"offset_too_large"}
