"""Form rules: the same answer in the browser and on the server (WP-046a S5b; REQ-INC-037).

A template's rules show, hide, require, lock or set fields when a condition over the form's
values holds ("if category is network, require site"). The browser evaluates them for instant
feedback; the server evaluates the same rules on every save, so an API or e-mail path cannot
get around them. The TypeScript twin lives in `frontend/packages/forms/src/rules/` and both
run the shared vectors in `docs/architecture/form-rule-vectors.json` (AC3).

The condition language is a deliberately small part of the list filter DSL, so its meaning can
be the same in both evaluators by construction:

- a leaf `{"field", "op", "value"}` with `op` one of eq, ne, in, not_in, is_null, is_not_null;
  `and` / `or` lists nest it (depth and size are capped);
- values compare as text (ids and codes are text on both sides); a missing value matches only
  `ne`, `not_in` and `is_null`, as in the filter DSL;
- a list value (tags, multiple choice): `eq` / `in` mean "includes", `ne` / `not_in`
  "excludes", `is_null` "missing or empty".

Evaluation is one pass, in rule order, over the values as submitted (a value a rule sets does
not trigger other rules: no loops, no order puzzles). Each matching rule's actions apply in
order, so a later rule wins over an earlier one for the same field:

- `show` / `hide`: whether the field is on the form. A hidden field is never required, and its
  value is cleared on save unless the action says `keep_value` (AC2).
- `require`: the field must have a value; the error code is `required` in both places (AC1).
- `lock`: the field cannot be changed by hand.
- `set`: the field takes this value when it is empty.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

RULES_MAX = 50
ACTIONS_MAX = 20
LEAVES_MAX = 20
DEPTH_MAX = 3
RULE_ID_MAX = 40
VALUES_MAX = 100


class RuleOp(StrEnum):
    """The condition operators a form rule may use."""

    EQ = "eq"
    NE = "ne"
    IN = "in"
    NOT_IN = "not_in"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


class RuleAction(StrEnum):
    """What a matching rule does to a field."""

    SHOW = "show"
    HIDE = "hide"
    REQUIRE = "require"
    LOCK = "lock"
    SET = "set"


_NO_VALUE = frozenset({RuleOp.IS_NULL, RuleOp.IS_NOT_NULL})
_LISTED = frozenset({RuleOp.IN, RuleOp.NOT_IN})


@dataclass(frozen=True)
class FieldState:
    """One field after the rules: on the form, required, locked."""

    shown: bool
    required: bool
    locked: bool = False
    keep_value: bool = False


@dataclass(frozen=True)
class FormState:
    """The whole form after the rules."""

    fields: Mapping[str, FieldState]
    # Values rules set because the field was empty (name -> value).
    set_values: Mapping[str, Any] = field(default_factory=dict)
    # Which rules matched, in order (for the designer's test panel and history).
    matched: Sequence[str] = ()


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


def evaluate(
    rules: Sequence[Mapping[str, Any]],
    base: Mapping[str, tuple[bool, bool]],
    values: Mapping[str, Any],
) -> FormState:
    """The form's fields after the rules.

    `base` is each field's (shown, required) from the template's own field settings; `values`
    the form's values as submitted. Rules must be validated (`rule_problems`) first.
    """
    shown = {name: s for name, (s, _r) in base.items()}
    required = {name: r for name, (_s, r) in base.items()}
    locked: set[str] = set()
    keep: set[str] = set()
    set_values: dict[str, Any] = {}
    matched: list[str] = []
    for rule in rules:
        if not matches(rule["when"], values):
            continue
        matched.append(str(rule["id"]))
        for action in rule["then"]:
            name, do = action["field"], RuleAction(action["do"])
            if do is RuleAction.SHOW:
                shown[name] = True
                keep.discard(name)
            elif do is RuleAction.HIDE:
                shown[name] = False
                if action.get("keep_value"):
                    keep.add(name)
                else:
                    keep.discard(name)
            elif do is RuleAction.REQUIRE:
                required[name] = True
            elif do is RuleAction.LOCK:
                locked.add(name)
            elif empty(values.get(name)):
                set_values[name] = action.get("value")
    names = set(shown) | set(required) | locked
    return FormState(
        fields={
            name: FieldState(
                shown=shown.get(name, True),
                # A hidden field is never required: nobody could fill it in.
                required=required.get(name, False) and shown.get(name, True),
                locked=name in locked,
                keep_value=name in keep,
            )
            for name in sorted(names)
        },
        set_values=set_values,
        matched=matched,
    )


def _condition_problems(  # noqa: C901, PLR0911 - one check per part of a condition, flat
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
                found += _condition_problems(
                    child, fields, f"{path}.{joiner}.{index}", depth + 1, leaves
                )
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
        ok = isinstance(value, list) and 0 < len(value) <= VALUES_MAX and all(map(_scalar, value))
        return [] if ok else [(f"{path}.value", "invalid_value")]
    return [] if _scalar(value) else [(f"{path}.value", "invalid_value")]


def _scalar(value: Any) -> bool:  # noqa: ANN401 - untrusted JSON
    return isinstance(value, str | int | bool) and (not isinstance(value, str) or len(value) <= 200)  # noqa: PLR2004 - a value's length


def rule_problems(  # noqa: C901, PLR0912 - one check per part of a rule, flat
    rules: Any,  # noqa: ANN401 - untrusted JSON
    fields: Iterable[str],
    *,
    fixed: Iterable[str] = (),
) -> list[tuple[str, str]]:
    """(path, code) for every part of the rules that is not valid; empty when they are.

    `fields` are the names the form has (built-in and `custom.<key>`); `fixed` those that are
    always shown and required (subject, requester): no rule may hide or lock them.
    """
    known, always = frozenset(fields), frozenset(fixed)
    if not isinstance(rules, list):
        return [("form_rules", "invalid_value")]
    if len(rules) > RULES_MAX:
        return [("form_rules", "too_many_values")]
    problems: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, rule in enumerate(rules):
        path = f"form_rules.{index}"
        if not isinstance(rule, Mapping) or set(rule) - {"id", "when", "then"}:
            problems.append((path, "invalid_value"))
            continue
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not 0 < len(rule_id) <= RULE_ID_MAX:
            problems.append((f"{path}.id", "invalid_value"))
        elif rule_id in seen:
            problems.append((f"{path}.id", "duplicate_value"))
        else:
            seen.add(rule_id)
        problems += _condition_problems(rule.get("when"), known, f"{path}.when", 0, [0])
        actions = rule.get("then")
        if not isinstance(actions, list) or not actions:
            problems.append((f"{path}.then", "required"))
            continue
        if len(actions) > ACTIONS_MAX:
            problems.append((f"{path}.then", "too_many_values"))
            continue
        for number, action in enumerate(actions):
            at = f"{path}.then.{number}"
            if not isinstance(action, Mapping) or set(action) - {
                "do",
                "field",
                "value",
                "keep_value",
            }:
                problems.append((at, "invalid_value"))
                continue
            if action.get("do") not in set(RuleAction):
                problems.append((f"{at}.do", "invalid_choice"))
                continue
            do, name = RuleAction(action["do"]), action.get("field")
            if name not in known:
                problems.append((f"{at}.field", "not_a_form_field"))
            elif name in always and do in {RuleAction.HIDE, RuleAction.LOCK}:
                problems.append((f"{at}.field", "field_always_required"))
            if do is RuleAction.SET and not _scalar(action.get("value")):
                problems.append((f"{at}.value", "invalid_value"))
            if do is not RuleAction.SET and "value" in action:
                problems.append((f"{at}.value", "invalid_value"))
            if "keep_value" in action and (
                do is not RuleAction.HIDE or not isinstance(action["keep_value"], bool)
            ):
                problems.append((f"{at}.keep_value", "invalid_value"))
    return problems


__all__ = [
    "ACTIONS_MAX",
    "DEPTH_MAX",
    "LEAVES_MAX",
    "RULES_MAX",
    "FieldState",
    "FormState",
    "RuleAction",
    "RuleOp",
    "empty",
    "evaluate",
    "matches",
    "rule_problems",
]
