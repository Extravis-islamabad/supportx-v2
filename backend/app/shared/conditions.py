"""The small condition language shared by form rules and request stages (WP-046a S5b; WP-047a).

One meaning everywhere, by construction (the coordinator, WP-047a S2 condition 4): the form
rules (`work_items.domain.form_rules`, with their TypeScript twin and the shared vectors in
`docs/architecture/form-rule-vectors.json`) and a catalogue item's approval stage conditions
(REQ-SR-032) use this one evaluator and this one validator.

- a leaf `{"field", "op", "value"}` with `op` one of eq, ne, in, not_in, is_null, is_not_null;
  `and` / `or` lists nest it (depth and size are capped);
- values compare as text (ids and codes are text on both sides); a missing value matches only
  `ne`, `not_in` and `is_null`, as in the filter DSL;
- a list value (tags, multiple choice): `eq` / `in` mean "includes", `ne` / `not_in`
  "excludes", `is_null` "missing or empty".
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

LEAVES_MAX = 20
DEPTH_MAX = 3
VALUES_MAX = 100


class RuleOp(StrEnum):
    """The condition operators a form rule may use."""

    EQ = "eq"
    NE = "ne"
    IN = "in"
    NOT_IN = "not_in"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


_NO_VALUE = frozenset({RuleOp.IS_NULL, RuleOp.IS_NOT_NULL})
_LISTED = frozenset({RuleOp.IN, RuleOp.NOT_IN})


def _text(value: Any) -> str:  # noqa: ANN401 - any form value
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).lower() if _uuidish(value) else str(value)


def _uuidish(value: Any) -> bool:  # noqa: ANN401 - any form value
    text = str(value)
    return len(text) == 36 and text.count("-") == 4  # noqa: PLR2004 - a UUID's shape


def empty(value: Any) -> bool:  # noqa: ANN401 - any form value
    """No value: missing, blank text or an empty list."""
    return value is None or value == "" or (isinstance(value, list) and not value)


def _leaf(op: RuleOp, wanted: Any, actual: Any) -> bool:  # noqa: ANN401 - validated JSON
    if op is RuleOp.IS_NULL:
        return empty(actual)
    if op is RuleOp.IS_NOT_NULL:
        return not empty(actual)
    choices = {_text(v) for v in (wanted if op in _LISTED else [wanted])}
    if empty(actual):
        return op in {RuleOp.NE, RuleOp.NOT_IN}
    have = {_text(v) for v in actual} if isinstance(actual, list) else {_text(actual)}
    if op in {RuleOp.EQ, RuleOp.IN}:
        return bool(have & choices)
    return not (have & choices)


def matches(condition: Mapping[str, Any], values: Mapping[str, Any]) -> bool:
    """Whether the (validated) condition holds for these form values."""
    if "and" in condition:
        return all(matches(c, values) for c in condition["and"])
    if "or" in condition:
        return any(matches(c, values) for c in condition["or"])
    return _leaf(RuleOp(condition["op"]), condition.get("value"), values.get(condition["field"]))


def _problems(  # noqa: C901, PLR0911 - one check per part of a condition, flat
    node: Any,  # noqa: ANN401 - untrusted JSON
    fields: frozenset[str],
    path: str,
    depth: int,
    leaves: list[int],
) -> list[tuple[str, str]]:
    if not isinstance(node, Mapping):
        return [(path, "invalid_value")]
    for joiner in ("and", "or"):
        if joiner in node:
            children = node[joiner]
            if len(node) != 1 or not isinstance(children, list) or not children:
                return [(path, "invalid_value")]
            if depth >= DEPTH_MAX:
                return [(path, "rule_too_deep")]
            found: list[tuple[str, str]] = []
            for index, child in enumerate(children):
                found += _problems(child, fields, f"{path}.{joiner}.{index}", depth + 1, leaves)
            return found
    leaves[0] += 1
    if leaves[0] > LEAVES_MAX:
        return [(path, "too_many_values")]
    if set(node) - {"field", "op", "value"}:
        return [(path, "invalid_value")]
    if node.get("field") not in fields:
        return [(f"{path}.field", "not_a_form_field")]
    if node.get("op") not in set(RuleOp):
        return [(f"{path}.op", "invalid_choice")]
    op, value = RuleOp(node["op"]), node.get("value")
    if op in _NO_VALUE:
        return [] if value is None else [(f"{path}.value", "invalid_value")]
    if op in _LISTED:
        ok = isinstance(value, list) and 0 < len(value) <= VALUES_MAX and all(map(scalar, value))
        return [] if ok else [(f"{path}.value", "invalid_value")]
    return [] if scalar(value) else [(f"{path}.value", "invalid_value")]


def scalar(value: Any) -> bool:  # noqa: ANN401 - untrusted JSON
    """A value a leaf may compare with: text (at most 200 characters), a number or a flag."""
    return isinstance(value, str | int | bool) and (not isinstance(value, str) or len(value) <= 200)  # noqa: PLR2004 - a value's length


def condition_problems(
    node: Any,  # noqa: ANN401 - untrusted JSON
    fields: frozenset[str],
    path: str,
) -> list[tuple[str, str]]:
    """What is wrong with a condition over these fields ([] when it may be saved)."""
    return _problems(node, fields, path, 0, [0])


def condition_fields(condition: Mapping[str, Any]) -> set[str]:
    """Every field a (validated) condition reads."""
    if "and" in condition or "or" in condition:
        found: set[str] = set()
        for child in condition.get("and") or condition.get("or") or []:
            found |= condition_fields(child)
        return found
    return {str(condition["field"])}


__all__ = [
    "DEPTH_MAX",
    "LEAVES_MAX",
    "VALUES_MAX",
    "RuleOp",
    "condition_fields",
    "condition_problems",
    "empty",
    "matches",
    "scalar",
]
