"""CI field access and custom-value rules, pure (ADR-047; 0175 part 2)."""

from app.modules.cmdb.domain import field_access as rules

ACCESS = {
    "ci": {"custom.salary": "hidden", "custom.licence": "masked", "custom.rack": "read_only"},
    "incident": {"custom.salary": "masked"},
}


def test_hidden_and_masked_are_withheld_and_every_rule_locks() -> None:
    unseen = rules.unseen(ACCESS, "ci")
    assert unseen.hidden == {"custom.salary"}
    assert unseen.masked == {"custom.licence"}
    assert unseen.custom_keys() == {"salary", "licence"}
    assert rules.read_only(ACCESS, "ci") == {"custom.salary", "custom.licence", "custom.rack"}
    assert rules.unseen({}, "ci").all == frozenset()


def test_without_and_refused() -> None:
    custom = {"salary": "S", "licence": "L", "rack": "R"}
    assert rules.without(custom, frozenset({"salary", "licence"})) == {"rack": "R"}
    assert rules.without(None, frozenset()) == {}
    locked = rules.read_only(ACCESS, "ci")
    assert rules.refused(["custom.rack", "custom.free"], locked) == ["custom.rack"]


def test_flat_spreads_custom_values_as_their_own_fields() -> None:
    snapshot = {"name": "SW-01", "custom": {"port": 48, "note": None}}
    assert rules.flat(snapshot) == {"name": "SW-01", "custom.port": 48, "custom.note": None}
    assert rules.flat({"name": "x"}) == {"name": "x"}


def test_dropped_names_live_fields_with_a_value_outside_the_new_type() -> None:
    custom = {"port": 48, "note": "kept", "gone": "old", "empty": None}
    known = ["port", "note", "empty"]  # "gone" was removed: not ours to judge
    assert rules.dropped(custom, kept=["note"], known=known) == ["port"]
    assert rules.dropped(custom, kept=known, known=known) == []
