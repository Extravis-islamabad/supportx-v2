"""Custom field rules, pure domain (WP-026; REQ-INC-014, D-087). No I/O."""

from decimal import Decimal

import pytest

from app.modules.metadata.domain.fields import (
    Choice,
    Definition,
    FieldType,
    Validation,
    clean_value,
    clean_values,
    definition_problems,
    key_from,
    missing_required,
    search_text,
)
from app.modules.metadata.infra.expressions import index_name, index_sql, value_sql


def test_keys_come_from_the_english_name_and_never_clash() -> None:
    assert key_from("Contract type", set()) == "contract_type"
    assert key_from("Contract type", {"contract_type"}) == "contract_type_2"
    assert key_from("Contract type", {"contract_type", "contract_type_2"}) == "contract_type_3"
    assert key_from("2nd line", set()) == "f_2nd_line"
    assert key_from("Café № 5", set()) == "cafe_no_5"
    assert key_from("!!", set()) == "field"
    assert key_from("x" * 80, set()) == "x" * 36


@pytest.mark.parametrize(
    ("kind", "value", "stored", "codes"),
    [
        (FieldType.TEXT, "  two   words ", "two words", []),
        (FieldType.TEXT, "x" * 251, "x" * 251, ["value_too_long"]),
        (FieldType.LONG_TEXT, "line 1\n\nline 2\n", "line 1\n\nline 2", []),
        (FieldType.INTEGER, "42", 42, []),
        (FieldType.INTEGER, 4.5, None, ["invalid_value"]),
        (FieldType.INTEGER, True, None, ["invalid_value"]),
        (FieldType.DECIMAL, "0.1", 0.1, []),
        (FieldType.DECIMAL, "1e20", None, ["invalid_value"]),
        (FieldType.DECIMAL, "NaN", None, ["invalid_value"]),
        (FieldType.DATE, "2026-02-29", None, ["invalid_value"]),
        (FieldType.DATE, "2028-02-29", "2028-02-29", []),
        (FieldType.DATETIME, "2026-10-26T12:00:00+05:00", "2026-10-26T07:00:00+00:00", []),
        (FieldType.DATETIME, "2026-10-26T12:00:00", None, ["timezone_required"]),
        (FieldType.YES_NO, False, False, []),
        (FieldType.YES_NO, "false", None, ["invalid_value"]),
        (FieldType.EMAIL, "a@b.co", "a@b.co", []),
        (FieldType.EMAIL, "a@b", "a@b", ["email_not_valid"]),
        (FieldType.PHONE, "+92 (300) 123-4567", "+92 (300) 123-4567", []),
        (FieldType.PHONE, "call me", "call me", ["phone_not_valid"]),
        (FieldType.URL, "https://x.example/a?b=c", "https://x.example/a?b=c", []),
        (FieldType.URL, "javascript:alert(1)", "javascript:alert(1)", ["url_not_valid"]),
        (FieldType.PERSON, "0192f0c1-0000-7000-8000-000000000001", None, []),
        (FieldType.PERSON, "someone", None, ["invalid_value"]),
        (FieldType.TEXT, "", None, []),
        (FieldType.MULTI_CHOICE, [], None, []),
    ],
)
def test_values_clean_by_type(
    kind: FieldType, value: object, stored: object, codes: list[str]
) -> None:
    cleaned, problems = clean_value(Definition(key="f", type=kind), value)
    if kind == FieldType.PERSON and not codes:
        stored = value
    assert (cleaned, problems) == (stored, codes)


def test_numbers_respect_min_and_max_exactly() -> None:
    rules = Validation(min=Decimal("0.1"), max=Decimal(10))
    cost = Definition(key="cost", type=FieldType.CURRENCY, validation=rules)
    assert clean_value(cost, "0.1") == (0.1, [])
    assert clean_value(cost, "0.09") == (None, ["below_minimum"])
    assert clean_value(cost, 10.000001) == (None, ["above_maximum"])


def test_text_lengths_and_pattern() -> None:
    code = Definition(
        key="code",
        type=FieldType.TEXT,
        validation=Validation(min_length=3, max_length=5, pattern=r"[A-Z]+-\d"),
    )
    assert clean_value(code, "AB-1") == ("AB-1", [])
    assert clean_value(code, "A1") == ("A1", ["value_too_short"])
    assert clean_value(code, "ABCDE-1") == ("ABCDE-1", ["value_too_long"])
    assert clean_value(code, "ab-1") == ("ab-1", ["pattern_mismatch"])


def test_retired_choices_stay_on_records_that_hold_them() -> None:
    floor = Definition(
        key="floor",
        type=FieldType.CHOICE,
        choices=(Choice("ground", {"en": "Ground"}, retired=True), Choice("first", {"en": "1"})),
    )
    assert clean_value(floor, "first") == ("first", [])
    assert clean_value(floor, "ground") == (None, ["invalid_choice"])
    assert clean_value(floor, "ground", current="ground") == ("ground", [])
    systems = Definition(
        key="systems",
        type=FieldType.MULTI_CHOICE,
        choices=(Choice("mail", {"en": "Mail"}, retired=True), Choice("vpn", {"en": "VPN"})),
    )
    assert clean_value(systems, ["vpn", "mail"], current=["mail"]) == (["vpn", "mail"], [])
    assert clean_value(systems, ["mail"]) == (None, ["invalid_choice"])


def test_unknown_and_retired_fields_take_no_new_values() -> None:
    known = {
        "room": Definition(key="room", type=FieldType.TEXT),
        "old": Definition(key="old", type=FieldType.TEXT, retired=True),
    }
    _, problems = clean_values(known, {"room": "B1", "old": "x", "ghost": 1})
    assert sorted(problems) == [("custom.ghost", "unknown_field"), ("custom.old", "field_retired")]
    # Sending a retired field's own old value again is not a change.
    cleaned, problems = clean_values(known, {"old": "x"}, current={"old": "x"})
    assert (cleaned, problems) == ({"old": "x"}, [])


def test_required_on_create_and_never_emptied_later() -> None:
    known = {
        "room": Definition(key="room", type=FieldType.TEXT, validation=Validation(required=True))
    }
    assert missing_required(known, {}, creating=True) == [("custom.room", "required")]
    # A field made required later does not block other edits of an older record ...
    assert missing_required(known, {}, creating=False, current={}) == []
    # ... only emptying it once filled.
    assert missing_required(known, {"room": None}, creating=False, current={"room": "B1"}) == [
        ("custom.room", "required")
    ]


@pytest.mark.parametrize(
    ("kind", "settings", "expected"),
    [
        (FieldType.CHOICE, {}, [("choices", "choices_required")]),
        (FieldType.TEXT, {"choices": [Choice("a1", {"en": "A"})]}, [("choices", "not_allowed")]),
        (
            FieldType.TEXT,
            {"validation": Validation(min=Decimal(1))},
            [("validation", "not_allowed")],
        ),
        (
            FieldType.DECIMAL,
            {"validation": Validation(min=Decimal(5), max=Decimal(1))},
            [("validation.max", "invalid_range")],
        ),
        (
            FieldType.TEXT,
            {"validation": Validation(pattern="(")},
            [("validation.pattern", "invalid_pattern")],
        ),
        (
            FieldType.TEXT,
            {"validation": Validation(pattern=r"(a+)+$")},
            [("validation.pattern", "invalid_pattern")],
        ),
        (
            FieldType.TEXT,
            {"validation": Validation(pattern=r"(\w*)*")},
            [("validation.pattern", "invalid_pattern")],
        ),
        (FieldType.TEXT, {"validation": Validation(pattern=r"(ab)+[0-9]{2}")}, []),
        (FieldType.CURRENCY, {}, [("currency", "invalid_currency")]),
        (FieldType.CURRENCY, {"currency": "SAR"}, []),
        (FieldType.TEXT, {"currency": "SAR"}, [("currency", "not_allowed")]),
        (FieldType.PERSON, {"default": "someone"}, [("default", "no_default_allowed")]),
        (FieldType.INTEGER, {"default": "1.5"}, [("default", "invalid_value")]),
    ],
)
def test_definitions_that_could_never_work_are_refused(
    kind: FieldType, settings: dict[str, object], expected: list[tuple[str, str]]
) -> None:
    args: dict[str, object] = {
        "choices": (),
        "validation": Validation(),
        "default": None,
        "currency": None,
    }
    args.update(settings)
    assert definition_problems(kind, **args) == expected  # type: ignore[arg-type]  # test table


def test_search_text_holds_only_free_text_of_known_fields() -> None:
    known = {
        "tag": Definition(key="tag", type=FieldType.TEXT),
        "mail": Definition(key="mail", type=FieldType.EMAIL),
        "seats": Definition(key="seats", type=FieldType.INTEGER),
        "floor": Definition(key="floor", type=FieldType.CHOICE),
    }
    values = {"tag": "LAP-1", "mail": "a@b.co", "seats": 4, "floor": "first", "gone": "old"}
    assert search_text(known, values) == "LAP-1 a@b.co"


def test_expressions_are_guarded_and_index_matches_filter() -> None:
    sql, _ = value_sql("work_items", "cost", FieldType.DECIMAL)
    assert sql == (
        "(CASE WHEN jsonb_typeof(work_items.custom -> 'cost') = 'number'"
        " THEN (work_items.custom ->> 'cost')::numeric END)"
    )
    assert sql in index_sql("work_items", "incident", "cost", FieldType.DECIMAL)
    assert index_name("incident", "cost", FieldType.DECIMAL) == "ix_cf_incident_decimal_cost"
    assert "USING gin" in index_sql("work_items", "incident", "tags", FieldType.MULTI_CHOICE)
    for unsafe in ("x'; DROP TABLE users; --", "Cost", "a"):
        with pytest.raises(ValueError, match="unsafe"):
            value_sql("work_items", unsafe, FieldType.TEXT)
