"""`set_state` restores app.state values, and no test patches app.state with setattr."""

import re
from pathlib import Path

import pytest
from starlette.datastructures import State

from tests.app_state import set_state

ROOT = Path(__file__).resolve().parents[1]
_SETATTR_ON_STATE = re.compile(r"monkeypatch\.(setattr|delattr)\([^,()]*\.state\s*,")


def test_set_state_puts_the_old_value_back() -> None:
    state = State({"settings": "original"})
    patch = pytest.MonkeyPatch()
    set_state(patch, state, "settings", "for one test")
    assert state.settings == "for one test"
    patch.undo()
    assert state.settings == "original"  # monkeypatch.setattr deletes it here (pytest >= 9.2)


def test_no_test_patches_app_state_with_setattr() -> None:
    found = [
        f"{path.relative_to(ROOT)}:{number}"
        for folder in ("tests", "app")
        for path in sorted((ROOT / folder).rglob("*.py"))
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if _SETATTR_ON_STATE.search(line)
    ]
    assert found == [], "use tests.app_state.set_state instead"
