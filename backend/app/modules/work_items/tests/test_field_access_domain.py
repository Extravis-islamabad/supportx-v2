"""Field access on work items (ADR-047 b1), pure: what is withheld, what may not change."""

from app.modules.work_items.domain.field_access import (
    BUILTIN,
    read_only,
    refused,
    unseen,
    without,
)

ACCESS = {"problem": {"root_cause": "read_only", "custom.salary": "masked", "symptoms": "hidden"}}


def test_role_rules_split_into_hidden_and_masked() -> None:
    found = unseen(ACCESS, "problem")
    assert found.hidden == {"symptoms"}
    assert found.masked == {"custom.salary"}
    assert found.custom_keys() == {"salary"}
    assert unseen(ACCESS, "incident").all == frozenset()


def test_an_older_gate_hides_whatever_a_role_rule_says() -> None:
    """Lane B's note 2: a read_only (or masked, or no) rule never shows the root cause to someone
    without view_root_cause."""
    found = unseen(ACCESS, "problem", also_hidden={"root_cause"})
    assert "root_cause" in found.hidden
    masked_too = unseen(
        {"problem": {"root_cause": "masked"}}, "problem", also_hidden={"root_cause"}
    )
    assert "root_cause" in masked_too.hidden
    assert "root_cause" not in masked_too.masked


def test_any_rule_makes_a_field_read_only() -> None:
    assert read_only(ACCESS, "problem") == {"root_cause", "custom.salary", "symptoms"}
    assert refused(["subject", "custom.salary"], read_only(ACCESS, "problem")) == ["custom.salary"]


def test_withheld_custom_values_are_left_out() -> None:
    assert without({"salary": "B7", "grade": "Senior"}, frozenset({"salary"})) == {
        "grade": "Senior"
    }
    assert without(None, frozenset({"salary"})) == {}


def test_core_fields_are_never_offered() -> None:
    offered = {f for fields in BUILTIN.values() for f in fields}
    assert not offered & {"subject", "description", "status", "priority", "requester_id",
                          "group_id", "technician_id"}  # fmt: skip
