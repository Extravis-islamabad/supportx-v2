"""The baseline compare's masked rule, pure (WP-053 S7b; ADR-047): changed or not, never values."""

from app.modules.cmdb.domain.field_access import MaskedChange, masked_changes

LIVE = ("serial", "secret", "budget", "gone")


def test_a_masked_field_says_only_whether_it_changed() -> None:
    found = masked_changes(
        {"secret": "old-value", "budget": 10, "serial": "A"},
        {"secret": "new-value", "budget": 10, "serial": "B"},
        frozenset({"custom.secret", "custom.budget"}),
        LIVE,
    )
    assert found == [
        MaskedChange("custom.budget", changed=False),
        MaskedChange("custom.secret", changed=True),
    ]
    for change in found:  # nothing of either value, in any form
        assert set(vars(change)) == {"field", "changed"}


def test_added_or_removed_on_one_side_is_a_change() -> None:
    found = masked_changes({}, {"secret": "x"}, frozenset({"custom.secret"}), LIVE)
    assert found == [MaskedChange("custom.secret", changed=True)]
    assert masked_changes({"secret": "x"}, None, frozenset({"custom.secret"}), LIVE) == [
        MaskedChange("custom.secret", changed=True)
    ]


def test_unmasked_and_removed_fields_are_not_listed() -> None:
    """An unmasked field is compared in the open (elsewhere); a field gone since shows nowhere."""
    found = masked_changes(
        {"serial": "A", "retired": "x"},
        {"serial": "B", "retired": "y"},
        frozenset({"custom.retired"}),
        LIVE,
    )
    assert found == []


def test_neither_side_holding_it_lists_nothing() -> None:
    assert masked_changes(None, None, frozenset({"custom.secret"}), LIVE) == []
