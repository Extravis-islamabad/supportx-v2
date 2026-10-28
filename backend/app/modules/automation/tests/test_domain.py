"""Business rules, routing and auto-assignment without I/O (WP-029)."""

from datetime import UTC, datetime, timedelta

from app.modules.automation.domain.assignment import (
    AssignMethod,
    Candidate,
    RoutingRuleDef,
    choose,
    route,
    weighted_load,
)
from app.modules.automation.domain.rules import (
    ActionMode,
    FieldKind,
    RuleAction,
    RuleDef,
    RuleEvent,
    RuleField,
    check_actions,
    check_conditions,
    matches,
    message_for,
    run_rules,
)

FIELDS = {
    "priority": RuleField(FieldKind.CODE, frozenset({"p1", "p2", "p3", "p4"}), settable=True),
    "status": RuleField(FieldKind.CODE, frozenset({"new", "awaiting_requester", "in_progress"})),
    "group_id": RuleField(FieldKind.REFERENCE, settable=True),
    "category_id": RuleField(FieldKind.REFERENCE, settable=True),
    "subject": RuleField(FieldKind.TEXT),
    "tags": RuleField(FieldKind.CODES, settable=True),
    "requester.department_id": RuleField(FieldKind.REFERENCE, derived=True),
    "requester.vip": RuleField(FieldKind.BOOLEAN, derived=True),
}


def rule(
    rule_id: str,
    actions: tuple[RuleAction, ...],
    conditions: dict[str, object] | None = None,
    *,
    stop: bool = False,
    events: frozenset[RuleEvent] = frozenset({RuleEvent.CREATE, RuleEvent.UPDATE}),
    site: str | None = None,
) -> RuleDef:
    return RuleDef(rule_id, f"Rule {rule_id}", events, conditions, actions, stop, site)


def set_(field: str, value: object, mode: ActionMode = ActionMode.FILL_EMPTY) -> RuleAction:
    return RuleAction("set", field, value, mode)


# --- conditions (REQ-RUL-002) --------------------------------------------------------------------


def test_req_rul_002_ac1_changed_from_fires_only_on_that_change() -> None:
    condition = {"field": "status", "op": "changed_from", "value": "awaiting_requester"}
    assert matches(condition, {"status": "awaiting_requester"}, {"status": "in_progress"})
    assert not matches(condition, {"status": "new"}, {"status": "in_progress"})
    assert not matches(condition, {"status": "in_progress"}, {"status": "in_progress"})
    assert not matches(condition, None, {"status": "in_progress"})  # a new record


def test_req_rul_002_ac2_requester_attributes_and_groups() -> None:
    condition = {
        "and": [
            {"field": "requester.department_id", "op": "eq", "value": "finance"},
            {"or": [{"field": "priority", "op": "in", "value": ["p1", "p2"]}]},
        ]
    }
    assert matches(condition, None, {"requester.department_id": "finance", "priority": "p2"})
    assert not matches(condition, None, {"requester.department_id": "finance", "priority": "p3"})
    assert not matches(condition, None, {"requester.department_id": "hr", "priority": "p1"})


def test_req_rul_002_ac3_unknown_fields_and_operators_are_refused_when_saved() -> None:
    assert check_conditions({"field": "nonsense", "op": "eq", "value": 1}, FIELDS) == [
        ("conditions.field", "unknown_field", {"field": "nonsense"})
    ]
    assert check_conditions({"field": "subject", "op": "gt", "value": "x"}, FIELDS)[0][1] == (
        "operator_not_allowed"
    )
    assert check_conditions({"field": "priority", "op": "eq", "value": "p9"}, FIELDS)[0][1] == (
        "invalid_choice"
    )
    assert check_conditions({"and": []}, FIELDS)[0][1] == "invalid_group"
    assert check_conditions({"field": "priority", "op": "is_null"}, FIELDS) == []


def test_tags_include_and_exclude() -> None:
    assert matches({"field": "tags", "op": "eq", "value": "vpn"}, None, {"tags": ["vpn", "x"]})
    assert matches({"field": "tags", "op": "ne", "value": "vpn"}, None, {"tags": ["x"]})


# --- actions and the run (REQ-RUL-001, 003, 004, 005) --------------------------------------------


def test_req_rul_003_ac1_ac2_fill_empty_keeps_a_value_overwrite_replaces_it() -> None:
    keep = run_rules(
        [rule("1", (set_("group_id", "b"),))], RuleEvent.CREATE, None, {"group_id": "a"}
    )
    assert (keep.values, keep.trace[0].kept) == ({}, ["group_id"])
    replace = run_rules(
        [rule("1", (set_("group_id", "b", ActionMode.OVERWRITE),))],
        RuleEvent.CREATE,
        None,
        {"group_id": "a"},
    )
    assert replace.values == {"group_id": "b"}
    assert replace.trace[0].changes == {"group_id": ("a", "b")}
    assert replace.made_by == {"group_id": ("1", "Rule 1")}


def test_req_rul_005_ac1_later_rules_see_earlier_changes() -> None:
    outcome = run_rules(
        [
            rule("1", (set_("priority", "p2"),)),
            rule(
                "2", (set_("tags", ["urgent"]),), {"field": "priority", "op": "eq", "value": "p2"}
            ),
        ],
        RuleEvent.CREATE,
        None,
        {},
    )
    assert outcome.values == {"priority": "p2", "tags": ["urgent"]}


def test_req_rul_005_ac2_stop_after_this_rule_says_why_later_ones_did_not_run() -> None:
    outcome = run_rules(
        [rule("1", (set_("priority", "p2"),), stop=True), rule("2", (set_("tags", ["x"]),))],
        RuleEvent.CREATE,
        None,
        {},
    )
    assert outcome.values == {"priority": "p2"}
    assert [(line.rule_id, line.outcome, line.stopped) for line in outcome.trace] == [
        ("1", "applied", True),
        ("2", "stopped_before", False),
    ]


def test_d097_rules_continue_unless_one_says_stop() -> None:
    outcome = run_rules(
        [rule("1", (set_("priority", "p2"),)), rule("2", (set_("tags", ["x"]),))],
        RuleEvent.CREATE,
        None,
        {},
    )
    assert set(outcome.values) == {"priority", "tags"}


def test_req_rul_004_a_refusal_stops_everything_with_the_message() -> None:
    refuse = RuleAction("refuse", message={"en": "Name an asset", "ar": "حدد أصلًا"})
    outcome = run_rules(
        [rule("1", (set_("priority", "p2"), refuse)), rule("2", (set_("tags", ["x"]),))],
        RuleEvent.CREATE,
        None,
        {},
    )
    assert outcome.refusal is not None
    assert message_for(outcome.refusal.message, "ar") == "حدد أصلًا"
    assert message_for(outcome.refusal.message, "ur") == "Name an asset"
    assert [line.rule_id for line in outcome.trace] == ["1"]


def test_req_rul_001_events_and_sites_limit_where_a_rule_runs() -> None:
    on_create = rule("1", (set_("priority", "p2"),), events=frozenset({RuleEvent.CREATE}))
    assert run_rules([on_create], RuleEvent.UPDATE, {}, {}).values == {}
    at_site = rule("2", (set_("priority", "p2"),), site="site-a")
    assert run_rules([at_site], RuleEvent.CREATE, None, {"site_id": "site-b"}).values == {}
    assert run_rules([at_site], RuleEvent.CREATE, None, {"site_id": "site-a"}).values == {
        "priority": "p2"
    }


def test_req_rul_029_actions_are_checked_when_saved() -> None:
    assert check_actions([], FIELDS) == [("actions", "required", {})]
    assert check_actions([{"kind": "set", "field": "status", "value": "new"}], FIELDS) == [
        ("actions.0.field", "field_not_settable", {"field": "status"})
    ]
    assert check_actions([{"kind": "set", "field": "priority", "value": "p9"}], FIELDS)[0][1] == (
        "invalid_choice"
    )
    assert check_actions([{"kind": "refuse", "message": {"en": " "}}], FIELDS)[0][1] == (
        "message_required"
    )
    assert (
        check_actions([{"kind": "set", "field": "requester.vip", "value": True}], FIELDS)[0][1]
        == "field_not_settable"
    )


# --- routing (REQ-ASG-001) -----------------------------------------------------------------------


def test_req_asg_001_rule_then_category_then_fallback() -> None:
    printers = RoutingRuleDef(
        "r1", "Printers", {"field": "category_id", "op": "eq", "value": "c-print"}, "g-print"
    )
    choice = route(
        [printers], {"category_id": "c-print"}, category_group=None, fallback_group="g-sd"
    )
    assert choice is not None
    assert (choice.group_id, choice.reason, choice.rule) == ("g-print", "rule", "Printers")
    by_category = route(
        [printers], {"category_id": "c-net"}, category_group="g-net", fallback_group="g-sd"
    )
    assert by_category is not None
    assert (by_category.group_id, by_category.reason) == (
        "g-net",
        "category",
    )
    fallback = route([printers], {}, category_group=None, fallback_group="g-sd")
    assert fallback is not None
    assert (fallback.group_id, fallback.reason) == ("g-sd", "fallback")


def test_wp024_the_entry_points_group_comes_after_the_rules_before_the_category() -> None:
    """A mailbox's support group (WP-024): rules first, then it, then the category's group."""
    printers = RoutingRuleDef(
        "r1", "Printers", {"field": "category_id", "op": "eq", "value": "c-print"}, "g-print"
    )
    by_rule = route(
        [printers],
        {"category_id": "c-print"},
        category_group="g-net",
        fallback_group="g-sd",
        entry_group="g-mail",
    )
    assert by_rule is not None
    assert by_rule.reason == "rule"
    by_entry = route(
        [printers],
        {"category_id": "c-net"},
        category_group="g-net",
        fallback_group="g-sd",
        entry_group="g-mail",
    )
    assert by_entry is not None
    assert (by_entry.group_id, by_entry.reason) == ("g-mail", "entry")


def test_req_asg_001_ac3_a_chosen_group_stays_unless_the_rule_overwrites() -> None:
    record = {"category_id": "c-print", "group_id": "g-mine"}
    condition = {"field": "category_id", "op": "eq", "value": "c-print"}
    keep = RoutingRuleDef("r1", "Printers", condition, "g-print")
    assert route([keep], record, category_group=None, fallback_group="g-sd") is None
    force = RoutingRuleDef("r1", "Printers", condition, "g-print", overwrite=True)
    choice = route([force], record, category_group=None, fallback_group="g-sd")
    assert choice is not None
    assert choice.group_id == "g-print"


# --- auto-assignment (REQ-ASG-003, 004, 006, 011) ------------------------------------------------

NOW = datetime(2026, 10, 27, 10, tzinfo=UTC)


def test_req_asg_003_ac1_nine_records_three_each() -> None:
    turns: dict[str, datetime | None] = {"a": None, "b": None, "c": None}
    given: dict[str, int] = {"a": 0, "b": 0, "c": 0}
    for n in range(9):
        candidates = [
            Candidate(u, available=True, load=0, open_count=0, last_assigned_at=turns[u])
            for u in turns
        ]
        choice = choose(AssignMethod.ROUND_ROBIN, candidates)
        assert choice.user_id is not None
        given[choice.user_id] += 1
        turns[choice.user_id] = NOW + timedelta(seconds=n)
    assert given == {"a": 3, "b": 3, "c": 3}


def test_req_asg_003_ac3_and_asg_006_unavailable_people_are_skipped() -> None:
    candidates = [
        Candidate("a", available=False, load=0, open_count=0, last_assigned_at=None),
        Candidate("b", available=True, load=0, open_count=0, last_assigned_at=NOW),
    ]
    assert choose(AssignMethod.ROUND_ROBIN, candidates).user_id == "b"
    nobody = choose(
        AssignMethod.ROUND_ROBIN,
        [Candidate("a", available=False, load=0, open_count=0, last_assigned_at=None)],
    )
    assert (nobody.user_id, nobody.reason) == (None, "nobody_available")


def test_req_asg_004_lowest_weighted_load_ties_to_the_least_recent() -> None:
    a = Candidate(
        "a",
        available=True,
        load=weighted_load(["p3", "p3"]),
        open_count=2,
        last_assigned_at=NOW - timedelta(hours=1),
    )
    b = Candidate(
        "b", available=True, load=weighted_load(["p1"]), open_count=1, last_assigned_at=NOW
    )
    choice = choose(AssignMethod.LOAD_BALANCING, [a, b])
    assert (choice.user_id, choice.loads) == ("a", {"a": 4, "b": 4})
    c = Candidate(
        "c", available=True, load=weighted_load(["p4"]), open_count=1, last_assigned_at=NOW
    )
    assert choose(AssignMethod.LOAD_BALANCING, [a, b, c]).user_id == "c"


def test_req_asg_011_everyone_at_the_cap_leaves_the_record_in_the_queue() -> None:
    full = [
        Candidate("a", available=True, load=20, open_count=10, last_assigned_at=None),
        Candidate("b", available=True, load=20, open_count=10, last_assigned_at=None),
    ]
    choice = choose(AssignMethod.ROUND_ROBIN, full, load_cap=10)
    assert (choice.user_id, choice.reason) == (None, "all_at_cap")
    one_free = [
        Candidate("a", available=True, load=20, open_count=10, last_assigned_at=None),
        Candidate("b", available=True, load=18, open_count=9, last_assigned_at=NOW),
    ]
    assert choose(AssignMethod.ROUND_ROBIN, one_free, load_cap=10).user_id == "b"


def test_req_asg_002_ac5_no_members_no_one_outside_the_group() -> None:
    choice = choose(AssignMethod.LOAD_BALANCING, [])
    assert (choice.user_id, choice.reason) == (None, "no_members")
