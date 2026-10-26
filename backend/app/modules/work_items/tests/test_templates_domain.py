"""Template rules and pick lists, pure domain (WP-020c; REQ-INC-035, REQ-WI-009 AC4)."""

from app.modules.work_items.domain.templates import (
    IMPACT_DETAILS_MAX,
    FieldRule,
    TemplateField,
    clean_impact_details,
    default_rules,
    is_admin_code,
    is_code,
    missing_required,
    new_value_code,
    order_problems,
    rule_problems,
    rules_from_json,
    rules_to_json,
)


def test_default_rules_show_everything_and_require_subject_and_requester() -> None:
    rules = default_rules()
    assert set(rules) == {f.value for f in TemplateField}
    assert all(r.shown for r in rules.values())
    assert {n for n, r in rules.items() if r.required} == {"subject", "requester_id"}
    assert rule_problems(rules, {}) == []


def test_rules_round_trip_and_missing_fields_get_defaults() -> None:
    rules = default_rules()
    rules["tags"] = FieldRule(shown=False)
    stored = rules_to_json(rules)
    del stored["level"]  # a template saved before a field existed
    back = rules_from_json(stored)
    assert back["tags"] == FieldRule(shown=False)
    assert back["level"] == FieldRule()


def test_req_wi_009_ac4_rules_that_can_never_work_are_named() -> None:
    rules = default_rules()
    rules["subject"] = FieldRule(required=False)
    rules["category_id"] = FieldRule(shown=False, required=True)
    rules["tags"] = FieldRule(requester_can_see=False, requester_can_fill=True)
    problems = rule_problems(rules, {"technician_id": "x"})
    assert sorted(problems) == [
        ("defaults.technician_id", "no_default_allowed"),
        ("fields.category_id", "hidden_required_needs_default"),
        ("fields.subject", "field_always_required"),
        ("fields.tags", "fill_needs_see"),
    ]
    # A hidden required field with a starting value is fine.
    assert ("fields.category_id", "hidden_required_needs_default") not in rule_problems(
        rules, {"category_id": "c"}
    )


def test_missing_required_ignores_fixed_fields_and_empty_values_count() -> None:
    rules = default_rules()
    rules["impact_details"] = FieldRule(required=True)
    rules["tags"] = FieldRule(required=True)
    assert missing_required(rules, {"impact_details": "  ", "tags": ["a"]}) == []
    assert missing_required(rules, {"impact_details": "", "tags": []}) == [
        ("impact_details", "required"),
        ("tags", "required"),
    ]


def test_impact_details_are_trimmed_plain_text_with_a_limit() -> None:
    assert clean_impact_details(None) == (None, [])
    assert clean_impact_details("  ") == (None, [])
    assert clean_impact_details(" Floor 2 ") == ("Floor 2", [])
    assert clean_impact_details("x" * (IMPACT_DETAILS_MAX + 1))[1] == ["value_too_long"]


def test_value_codes_and_reorders() -> None:
    code = new_value_code()
    assert is_code(code)
    assert is_admin_code(code)
    assert not is_admin_code("tier_1")
    assert order_problems(["a", "b"], ["b", "a"]) == []
    assert order_problems(["a", "b"], ["a"]) == ["order_must_list_every_value"]
    assert order_problems(["a", "b"], ["a", "a"]) == ["order_must_list_every_value"]
