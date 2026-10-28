"""Resolving, closing and reopening rules without I/O (WP-020f)."""

from datetime import UTC, datetime

from app.modules.work_items.domain.closure import (
    OpenItem,
    OpenWorkKind,
    OpenWorkMode,
    add_business_days,
    auto_close_due,
    decide_open_work,
    is_empty,
    missing_fields,
    open_work_modes,
    rule_field_problems,
    within_reopen_window,
)


def test_req_inc_094_missing_fields_in_the_admins_order() -> None:
    values = {"resolution": "<p></p>", "category_id": None, "closure_code": "fixed"}
    custom = {"cost": 12, "notes": ""}
    required = ["category_id", "resolution", "closure_code", "custom.cost", "custom.notes"]
    assert missing_fields(required, values, custom) == ["category_id", "resolution", "custom.notes"]


def test_req_inc_094_empty_rich_text_counts_as_missing() -> None:
    assert is_empty("<p>&nbsp;</p>")
    assert is_empty("  ")
    assert is_empty([])
    assert not is_empty("<p>Restarted the spooler</p>")
    assert not is_empty(0)


def test_req_inc_094_only_known_fields_can_be_required() -> None:
    assert rule_field_problems(
        ["resolution", "custom.cost", "custom.gone", "colour"], ["cost"]
    ) == [
        "custom.gone",
        "colour",
    ]


def test_req_inc_095_defaults_warn_on_tasks_and_block_on_approvals() -> None:
    modes = open_work_modes({})
    items = [
        OpenItem(OpenWorkKind.TASKS, "Replace toner"),
        OpenItem(OpenWorkKind.APPROVALS, "Manager approval"),
    ]
    decision = decide_open_work(items, modes)
    assert [i.title for i in decision.to_confirm] == ["Replace toner"]
    assert [i.title for i in decision.blocking] == ["Manager approval"]


def test_req_inc_095_ac2_an_admin_turns_a_warning_into_a_block() -> None:
    modes = open_work_modes({"tasks": "block", "nonsense": "block", "approvals": "maybe"})
    assert modes[OpenWorkKind.TASKS] == OpenWorkMode.BLOCK
    assert modes[OpenWorkKind.APPROVALS] == OpenWorkMode.BLOCK  # an unknown mode keeps the default
    decision = decide_open_work([OpenItem(OpenWorkKind.TASKS, "Replace toner")], modes)
    assert decision.blocking
    assert not decision.needs_confirmation


def test_req_inc_096_business_days_skip_the_weekend() -> None:
    friday = datetime(2026, 10, 30, 16, 0, tzinfo=UTC)
    assert add_business_days(friday, 3) == datetime(2026, 11, 4, 16, 0, tzinfo=UTC)  # Wednesday
    saturday = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
    assert add_business_days(saturday, 1) == datetime(2026, 11, 2, 9, 0, tzinfo=UTC)  # Monday


def test_req_inc_096_never_auto_closes_without_telling_the_requester() -> None:
    told = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
    assert auto_close_due(None, 3) is None  # the requester was never told
    assert auto_close_due(told, None) is None  # auto-close off
    assert auto_close_due(told, 3) == datetime(2026, 10, 29, 9, 0, tzinfo=UTC)


def test_req_inc_098_reopen_window() -> None:
    closed = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    assert within_reopen_window(closed, datetime(2026, 10, 22, 12, 0, tzinfo=UTC), 7)
    assert not within_reopen_window(closed, datetime(2026, 10, 28, 12, 1, tzinfo=UTC), 7)
    assert not within_reopen_window(None, datetime(2026, 10, 22, tzinfo=UTC), 7)
