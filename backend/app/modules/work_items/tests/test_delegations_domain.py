"""Approval delegation and restart rules (WP-047a S3b; REQ-SR-035, -041): pure, no I/O."""

import uuid
from datetime import UTC, datetime, timedelta

from app.modules.work_items.domain.delegations import (
    MAX_DAYS,
    QUANTITY,
    REQUESTED_FOR,
    Window,
    current_round,
    overlaps,
    problems,
    restart_keys,
)

ANN, BOB = uuid.UUID(int=1), uuid.UUID(int=2)
MON = datetime(2026, 11, 23, 0, 0, tzinfo=UTC)
WEEK = Window(MON, MON + timedelta(days=7))


def test_condition_1_never_oneself_both_ends_and_capped() -> None:
    assert problems(ANN, BOB, WEEK) == []
    assert problems(ANN, ANN, WEEK) == [("delegate_id", "delegate_is_delegator")]
    assert problems(ANN, BOB, Window(MON, MON)) == [("ends_at", "end_before_start")]
    too_long = Window(MON, MON + timedelta(days=MAX_DAYS, seconds=1))
    assert problems(ANN, BOB, too_long) == [("ends_at", "delegation_too_long")]
    assert problems(ANN, BOB, Window(MON, MON + timedelta(days=MAX_DAYS))) == []


def test_a_window_is_active_from_its_start_until_its_end_or_its_early_end() -> None:
    assert not WEEK.active_at(MON - timedelta(seconds=1))
    assert WEEK.active_at(MON)
    assert not WEEK.active_at(MON + timedelta(days=7))  # the end is not included
    ended = Window(WEEK.starts_at, WEEK.ends_at, ended_at=MON + timedelta(days=2))
    assert not ended.active_at(MON + timedelta(days=3))


def test_one_delegation_at_a_time_per_delegator() -> None:
    next_week = Window(MON + timedelta(days=7), MON + timedelta(days=14))
    assert not overlaps(next_week, [WEEK])  # back to back is fine
    assert overlaps(Window(MON + timedelta(days=6), MON + timedelta(days=8)), [WEEK])
    ended = Window(WEEK.starts_at, WEEK.ends_at, ended_at=MON + timedelta(days=1))
    assert not overlaps(Window(MON + timedelta(days=2), MON + timedelta(days=3)), [ended])


def test_041_only_marked_changes_restart() -> None:
    """AC1: a marked answer, or the quantity when the item says so; AC2: nothing else."""
    before, after = {"model": "air", "colour": "silver"}, {"model": "pro", "colour": "black"}
    assert restart_keys(before, after, ["model"]) == ["model"]
    assert restart_keys(before, after, []) == []  # AC2: no question is marked
    assert restart_keys({}, {}, [], quantity=(1, 3), on_quantity=True) == [QUANTITY]
    assert restart_keys({}, {}, [], quantity=(1, 3)) == []  # the item does not ask it
    assert restart_keys({}, {}, [], requested_for=(ANN, BOB), on_requested_for=True) == [
        REQUESTED_FOR
    ]


def test_the_engine_counts_the_latest_round() -> None:
    assert current_round([1, 1, 2, 2]) == 2
    assert current_round([]) == 1
