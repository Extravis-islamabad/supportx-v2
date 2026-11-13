"""Form rules (REQ-INC-037), without I/O: the shared vectors the browser runs too (AC3)."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.modules.work_items.domain.form_rules import evaluate, rule_problems

VECTORS = json.loads(
    (Path(__file__).parents[5] / "docs/architecture/form-rule-vectors.json").read_text("utf-8")
)
BASE: dict[str, tuple[bool, bool]] = {
    name: (pair[0], pair[1]) for name, pair in VECTORS["base"].items()
}
FIELDS = frozenset(BASE)
FIXED = ("subject", "requester_id")


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda c: c["name"])
def test_vector(case: dict[str, Any]) -> None:
    assert rule_problems(case["rules"], FIELDS, fixed=FIXED) == []
    state = evaluate(case["rules"], BASE, case["values"])
    expect = case["expect"]
    for name, wanted in expect["fields"].items():
        got = state.fields[name]
        assert {
            "shown": got.shown,
            "required": got.required,
            "locked": got.locked,
            "keep_value": got.keep_value,
        } == wanted, name
    assert dict(state.set_values) == expect["set_values"]
    assert list(state.matched) == expect["matched"]


@pytest.mark.parametrize("case", VECTORS["invalid"], ids=lambda c: c["name"])
def test_invalid_vector(case: dict[str, Any]) -> None:
    assert [list(p) for p in rule_problems(case["rules"], FIELDS, fixed=FIXED)] == case["problems"]
