"""CMDB domain rules, without I/O (WP-053 S1)."""

from app.modules.cmdb.domain import types as domain


def _attr(key: str, kind: str = "text", **extra: object) -> dict[str, object]:
    return {"key": key, "type": kind, "names": {"en": key.title()}, **extra}


PARENTS = {"server": "hardware", "hardware": None, "blade": "server"}


def test_chain_and_depth_follow_the_tree() -> None:
    assert domain.chain("blade", PARENTS) == ["blade", "server", "hardware"]
    assert domain.depth("hardware", PARENTS) == 1
    assert domain.depth("blade", PARENTS) == 3


def test_a_type_never_goes_below_itself() -> None:
    assert domain.would_loop("hardware", "blade", PARENTS)
    assert domain.would_loop("server", "server", PARENTS)
    assert not domain.would_loop("blade", "hardware", PARENTS)
    assert not domain.would_loop("blade", None, PARENTS)
    # A loop already stored is cut, never followed forever.
    assert domain.chain("x", {"x": "y", "y": "x"}) == ["x", "y"]


def test_attributes_are_inherited_root_first_and_the_nearest_wins() -> None:
    attributes = {
        "hardware": [_attr("rack_unit", "number"), _attr("serial")],
        "server": [_attr("os")],
        "blade": [_attr("serial", required=True)],
    }
    found = domain.inherited("blade", PARENTS, attributes)
    assert [(a["key"], a["defined_on"]) for a in found] == [
        ("rack_unit", "hardware"),
        ("serial", "blade"),
        ("os", "server"),
    ]
    assert found[1]["required"] is True


def test_sensitive_attributes_are_refused() -> None:
    problems = domain.attribute_problems([_attr("pin", sensitive=True)])
    assert problems == [domain.Problem("attributes[0].sensitive", domain.SENSITIVE_UNSUPPORTED)]
    assert domain.SENSITIVE_UNSUPPORTED == "custom_field_sensitive_unsupported"
    assert domain.attribute_problems([_attr("pin", sensitive=False)]) == []


def test_attribute_definitions_are_checked() -> None:
    problems = domain.attribute_problems(
        [
            _attr("Bad Key"),
            _attr("ok", "colour"),
            _attr("ok"),
            {"key": "nameless", "type": "text", "names": {}},
            _attr("pick", "choice", choices=[]),
        ]
    )
    assert {(p.field, p.code) for p in problems} == {
        ("attributes[0].key", "invalid_key"),
        ("attributes[1].type", "invalid_choice"),
        ("attributes[2].key", "duplicate"),
        ("attributes[3].names", "required"),
        ("attributes[4].choices", "invalid_value"),
    }
    assert domain.attribute_problems("nope") == [domain.Problem("attributes", "invalid_value")]


def test_values_are_checked_against_their_attributes() -> None:
    definitions = [
        _attr("rack_unit", "number"),
        _attr("bought", "date"),
        _attr("virtual", "boolean"),
        _attr("tier", "choice", choices=["gold", "silver"]),
        _attr("owner_note", required=True),
    ]
    good = {"rack_unit": 4, "bought": "2026-01-31", "virtual": False, "tier": "gold"}
    assert domain.custom_problems({**good, "owner_note": "x"}, definitions, creating=True) == []
    bad = {"rack_unit": True, "bought": "31/01/2026", "virtual": "no", "tier": "bronze", "x": 1}
    found = {(p.field, p.code) for p in domain.custom_problems(bad, definitions, creating=True)}
    assert found == {
        ("custom.rack_unit", "invalid_value"),
        ("custom.bought", "invalid_value"),
        ("custom.virtual", "invalid_value"),
        ("custom.tier", "invalid_choice"),
        ("custom.x", "unknown_attribute"),
        ("custom.owner_note", "required"),
    }
    # An edit never asks again for a required value it does not touch.
    assert domain.custom_problems({}, definitions, creating=False) == []


def test_a_type_change_lists_the_values_lost() -> None:
    custom = {"firmware": "7.2", "rack_unit": 3, "empty": None}
    assert domain.lost_on_change(custom, [_attr("rack_unit", "number")]) == ["firmware"]


def test_every_field_code_is_in_the_labelled_set() -> None:
    codes = {domain.SENSITIVE_UNSUPPORTED, "cmdb_ci_type_loop", "cmdb_ci_type_too_deep"}
    assert codes <= domain.FIELD_PROBLEMS
