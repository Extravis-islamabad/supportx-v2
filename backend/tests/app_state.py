"""Replace a value on a Starlette `app.state` for one test, restored afterwards.

Calling monkeypatch.setattr on `app.state` is not safe: from pytest 9.2, monkeypatch
reads an instance's old value from its `__dict__`, but Starlette's `State` keeps its values in
its own `_state` dict. pytest then sees no old value and *deletes* the attribute on undo, so a
shared fixture's teardown that reads `app.state.settings` fails with "'State' object has no
attribute 'settings'". Patching the dict itself is restored correctly by every pytest version.
"""

from typing import Any

import pytest
from starlette.datastructures import State


def set_state(monkeypatch: pytest.MonkeyPatch, state: State, name: str, value: object) -> None:
    """`state.<name> = value` for this test only."""
    values: dict[str, Any] = state._state  # noqa: SLF001 - see the module docstring
    monkeypatch.setitem(values, name, value)
