"""StatusMachine: validation of the table and the fixed action order."""

import pytest

from app.shared.domain import InvalidTransition, StatusMachine

TABLE = {
    "open": {"resolve": "resolved", "cancel": "cancelled"},
    "resolved": {"reopen": "open", "close": "closed"},
    "closed": {},
    "cancelled": {},
}


def test_order_defaults_to_first_appearance() -> None:
    machine = StatusMachine(TABLE)
    assert machine.actions == ("resolve", "cancel", "reopen", "close")
    assert machine.statuses == ("open", "resolved", "closed", "cancelled")


def test_explicit_order_is_kept_everywhere() -> None:
    machine = StatusMachine(TABLE, order=("reopen", "resolve", "close", "cancel"))
    assert machine.actions_from("open") == ["resolve", "cancel"]
    assert machine.actions_from("resolved") == ["reopen", "close"]
    assert machine.actions_from("unknown") == []


@pytest.mark.parametrize("order", [("resolve",), ("resolve", "cancel", "reopen", "close", "x")])
def test_order_must_name_every_action_once(order: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="must name each action once"):
        StatusMachine(TABLE, order=order)


def test_unknown_target_status_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="unknown status"):
        StatusMachine({"open": {"close": "closed"}})


def test_apply() -> None:
    machine = StatusMachine(TABLE)
    assert machine.apply("open", "resolve") == "resolved"
    with pytest.raises(InvalidTransition, match="'close' is not allowed from 'open'"):
        machine.apply("open", "close")
    # The table is frozen: nobody can add a move at runtime.
    with pytest.raises(TypeError):
        machine.transitions["closed"]["reopen"] = "open"  # type: ignore[index]  # proves read-only
