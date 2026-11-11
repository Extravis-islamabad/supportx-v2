"""Re-approval rules, pure (WP-045b S4; REQ-CHG-053)."""

from datetime import UTC, datetime, timedelta

from app.modules.work_items.domain.change_risk import RiskLevel
from app.modules.work_items.domain.reapproval import (
    DEFAULT_POLICY,
    OnChange,
    Snapshot,
    Watched,
    compare,
    policy_from,
    policy_json,
    policy_problems,
    restarts,
)

START = datetime(2026, 11, 20, 22, 0, tzinfo=UTC)
APPROVED = Snapshot(START, START + timedelta(hours=2), RiskLevel.MEDIUM, {"backout": 2})


def moved(minutes: int) -> Snapshot:
    shift = timedelta(minutes=minutes)
    return Snapshot(
        START + shift, START + timedelta(hours=2) + shift, RiskLevel.MEDIUM, {"backout": 2}
    )


def test_req_chg_053_ac1_a_window_moved_beyond_the_tolerance_restarts() -> None:
    changes = compare(APPROVED, moved(180), DEFAULT_POLICY)
    assert [c.field for c in changes] == ["window_start", "window_end"]
    assert restarts(changes)


def test_a_window_moved_within_the_tolerance_only_notifies() -> None:
    changes = compare(APPROVED, moved(30), DEFAULT_POLICY)
    assert {c.effect for c in changes} == {OnChange.NOTIFY}
    assert not restarts(changes)


def test_req_chg_053_ac2_a_raised_risk_restarts_a_lowered_one_notifies() -> None:
    higher = Snapshot(APPROVED.window_start, APPROVED.window_end, RiskLevel.HIGH, {"backout": 2})
    lower = Snapshot(APPROVED.window_start, APPROVED.window_end, RiskLevel.LOW, {"backout": 2})
    assert restarts(compare(APPROVED, higher, DEFAULT_POLICY))
    [change] = compare(APPROVED, lower, DEFAULT_POLICY)
    assert (change.field, change.effect) == ("risk", OnChange.NOTIFY)


def test_req_chg_053_ac3_plans_are_listed_field_by_field_and_notify() -> None:
    edited = Snapshot(
        APPROVED.window_start, APPROVED.window_end, RiskLevel.MEDIUM, {"backout": 3, "test": 1}
    )
    changes = compare(APPROVED, edited, DEFAULT_POLICY)
    assert [(c.field, c.before, c.after) for c in changes] == [
        ("plans.backout", 2, 3),
        ("plans.test", 0, 1),
    ]
    assert not restarts(changes)


def test_the_admin_chooses_per_field_and_ignored_fields_are_not_listed() -> None:
    policy = policy_from(
        {"on_change": {"window": "ignore", "plans": "restart"}, "tolerance_minutes": 0}
    )
    assert policy.on_change[Watched.WINDOW] is OnChange.IGNORE
    assert compare(APPROVED, moved(600), policy) == []
    edited = Snapshot(APPROVED.window_start, APPROVED.window_end, RiskLevel.MEDIUM, {"backout": 3})
    assert restarts(compare(APPROVED, edited, policy))


def test_a_policy_round_trips_and_is_checked() -> None:
    assert policy_from(policy_json(DEFAULT_POLICY)) == DEFAULT_POLICY
    assert policy_from(None) == DEFAULT_POLICY
    assert set(
        policy_problems({"on_change": {"cis": "restart", "risk": "maybe"}, "tolerance_minutes": -1})
    ) == {
        ("reapproval.on_change.cis", "not_a_field"),
        ("reapproval.on_change.risk", "invalid_choice"),
        ("reapproval.tolerance_minutes", "out_of_range"),
    }


def test_a_snapshot_round_trips() -> None:
    assert Snapshot.from_json(APPROVED.to_json()) == APPROVED
