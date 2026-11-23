"""Task details, dependencies and template specs (WP-046a S1). Pure rules, no I/O."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.modules.work_items.domain.tasks import (
    TaskSpec,
    creates_loop,
    detail_problems,
    open_predecessors,
    specs_of,
)

NOW = datetime(2026, 11, 11, 9, tzinfo=UTC)


def test_req_inc_073_ac1_an_end_before_its_start_is_refused() -> None:
    assert detail_problems(
        {"scheduled_start": NOW, "scheduled_end": NOW - timedelta(minutes=1)}
    ) == [("scheduled_end", "end_before_start")]
    assert detail_problems({"actual_start": NOW, "actual_end": NOW - timedelta(hours=1)}) == [
        ("actual_end", "end_before_start")
    ]
    assert detail_problems({"scheduled_start": NOW, "scheduled_end": NOW}) == []


def test_details_stay_in_range_and_a_reminder_needs_a_scheduled_start() -> None:
    assert detail_problems({"percent_complete": 101}) == [("percent_complete", "out_of_range")]
    assert detail_problems({"extra_cost": Decimal(-1)}) == [("extra_cost", "out_of_range")]
    assert detail_problems({"estimated_minutes": -5}) == [("estimated_minutes", "out_of_range")]
    assert detail_problems({"remind_before_minutes": 30}) == [
        ("remind_before_minutes", "needs_scheduled_start")
    ]
    assert detail_problems({"remind_before_minutes": 30, "scheduled_start": NOW}) == []


def test_req_inc_075_ac3_a_dependency_loop_is_found() -> None:
    edges = {"b": {"a"}, "c": {"b"}}  # c waits for b, b waits for a
    assert creates_loop(edges, "a", ["c"])  # a waiting for c closes a -> c -> b -> a
    assert not creates_loop(edges, "d", ["c"])
    assert creates_loop({}, "a", ["a"])


def test_req_inc_075_open_predecessors_are_those_not_finished() -> None:
    statuses = {"a": "done", "b": "in_progress", "c": "canceled", "d": "open"}
    assert open_predecessors(["a", "b", "c", "d"], statuses) == ["b", "d"]


def test_req_inc_074_template_specs_are_checked_each_by_place() -> None:
    found = specs_of([{"title": " Back up "}, {"title": "", "priority": "urgent"}])
    assert found == [("tasks.1.title", "required"), ("tasks.1.priority", "invalid_choice")]
    assert specs_of([]) == [("tasks", "required")]
    assert specs_of([{"title": "x"}] * 21) == [("tasks", "too_many_items")]
    assert specs_of([{"title": " Back up ", "estimated_minutes": 30}]) == [
        TaskSpec(title="Back up", estimated_minutes=30)
    ]
