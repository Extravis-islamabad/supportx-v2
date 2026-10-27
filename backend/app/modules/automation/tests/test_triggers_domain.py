"""Triggers, transition rules and the loop guard (WP-029 part 2), without I/O."""

from app.modules.automation.domain.rules import FieldKind, RuleField, matches
from app.modules.automation.domain.triggers import (
    DEPTH_CAP,
    RATE_CAP,
    Cause,
    ChainLink,
    LoopStop,
    People,
    Relative,
    TransitionRule,
    before_from,
    change_fields,
    check_after_actions,
    check_confirmation,
    check_trigger,
    loop_stop,
    may_run,
)

FIELDS = {
    "status": RuleField(FieldKind.CODE, frozenset({"new", "resolved"})),
    "priority": RuleField(FieldKind.CODE, frozenset({"p1", "p2"}), settable=True),
    "tags": RuleField(FieldKind.CODES, settable=True),
}
A, B = ChainLink("t-a", "A"), ChainLink("t-b", "B")


def test_req_rul_028_ac2_a_trigger_never_fires_on_its_own_change_unless_allowed() -> None:
    cause = Cause().then(A)
    assert (
        loop_stop(cause, "t-a", fire_on_own_change=False, recent_changes=0) == LoopStop.OWN_CHANGE
    )
    assert loop_stop(cause, "t-a", fire_on_own_change=True, recent_changes=0) is None
    assert loop_stop(cause, "t-b", fire_on_own_change=False, recent_changes=0) is None


def test_req_rul_028_ac1_two_triggers_stop_at_the_depth_cap_and_both_are_named() -> None:
    cause = Cause()
    for step in range(DEPTH_CAP):
        cause = cause.then(A if step % 2 == 0 else B)
    assert loop_stop(cause, "t-a", fire_on_own_change=True, recent_changes=0) == LoopStop.DEPTH
    assert cause.names() == ["A", "B"]


def test_req_rul_028_the_per_record_rate_cap() -> None:
    assert loop_stop(Cause(), "t-a", fire_on_own_change=False, recent_changes=RATE_CAP) == (
        LoopStop.RATE
    )
    assert loop_stop(Cause(), "t-a", fire_on_own_change=False, recent_changes=RATE_CAP - 1) is None


def test_changed_ops_work_from_an_event_that_names_fields_only() -> None:
    after = {"priority": "p1", "status": "resolved"}
    before = before_from(after, ["priority", "status"], {"status": "new"})
    assert matches({"field": "priority", "op": "changed_to", "value": "p1"}, before, after)
    assert matches({"field": "status", "op": "changed_from", "value": "new"}, before, after)
    assert not matches({"field": "priority", "op": "changed_from", "value": "p2"}, before, after)


def test_req_rul_029_a_trigger_is_checked_when_saved() -> None:
    good = {
        "events": ["status_changed"],
        "conditions": {"field": "status", "op": "changed_from", "value": "new"},
        "actions": [
            {"kind": "set", "field": "priority", "value": "p1"},
            {"kind": "note", "text": "x"},
        ],
    }
    assert check_trigger(good, FIELDS) == []
    bad = {
        "events": ["nonsense"],
        "conditions": {"field": "priority", "op": "changed_from", "value": "p1"},
        "actions": [
            {"kind": "note", "text": " "},
            {"kind": "set", "field": "status", "value": "new"},
        ],
    }
    codes = {(path, code) for path, code, _ in check_trigger(bad, FIELDS)}
    assert codes == {
        ("events", "invalid_choice"),
        ("conditions", "operator_not_allowed"),
        ("actions.0.text", "required"),
        ("actions.1.field", "field_not_settable"),
    }


def test_after_actions_name_their_own_index_and_refuse_a_field_set_twice() -> None:
    actions = [
        {"kind": "note", "text": "x"},
        {"kind": "set", "field": "priority", "value": "p9"},
        {"kind": "set", "field": "priority", "value": "p1"},
    ]
    codes = {(path, code) for path, code, _ in check_after_actions(actions, FIELDS)}
    assert codes == {("actions.1.value", "invalid_choice"), ("actions.2.field", "field_set_twice")}


def test_confirmation_needs_english_first() -> None:
    assert check_confirmation(None) == []
    assert check_confirmation({"ar": "x"}) == [("confirmation.en", "message_required", {})]
    assert check_confirmation({"en": "Sure?", "ar": "متأكد؟"}) == []


def test_req_wf_004_who_may_run_any_of_roles_groups_or_relatives() -> None:
    person = People(
        "u", frozenset({"technician"}), frozenset({"g1"}), frozenset({Relative.ASSIGNEE})
    )
    assert may_run(TransitionRule(), person)
    assert may_run(TransitionRule(relatives=frozenset({Relative.ASSIGNEE})), person)
    assert may_run(TransitionRule(group_ids=frozenset({"g1"})), person)
    assert not may_run(
        TransitionRule(
            roles=frozenset({"tenant_admin"}), relatives=frozenset({Relative.REQUESTER})
        ),
        person,
    )


def test_req_wf_003_offered_when_names_change_operators_to_refuse() -> None:
    tree = {
        "and": [
            {"field": "priority", "op": "eq", "value": "p1"},
            {"field": "status", "op": "changed_to", "value": "new"},
        ]
    }
    assert change_fields(tree) == ["status"]
