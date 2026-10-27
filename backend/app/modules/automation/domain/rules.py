"""Business rules without I/O (WP-029; REQ-RUL-001..005, REQ-RUL-029; ADR-034).

A record is seen as a flat snapshot: field name → JSON value (IDs as text, codes as codes,
custom fields as `custom.<key>`, the requester's attributes as `requester.<name>`). Conditions
use the shared filter grammar's shape (`{field, op, value}`, `{and: [...]}`, `{or: [...]}`) with
three more operators for updates: `changed`, `changed_from`, `changed_to`. Rules run in order;
each sees what the rules before it changed; "stop after this rule" ends the run when it matches.
"""

import dataclasses
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

JsonValue = Any  # a snapshot value: str, int, float, bool, None or a list of codes

MAX_RULES = 200
MAX_ACTIONS = 20
MAX_DEPTH = 5
MAX_CONDITIONS = 30
MAX_MESSAGE = 500
LANGUAGES = ("en", "ar", "ur")
NAME_MAX = 200
_CUSTOM = re.compile(r"^custom\.[a-z][a-z0-9_]{1,39}$")


class RuleEvent(StrEnum):
    """When a business rule runs (REQ-RUL-001)."""

    CREATE = "create"
    UPDATE = "update"


class RuleState(StrEnum):
    """A draft never runs (REQ-RUL-029); a disabled rule is kept but never runs."""

    DRAFT = "draft"
    ENABLED = "enabled"
    DISABLED = "disabled"


class RuleOp(StrEnum):
    """Condition operators: the filter grammar's comparisons plus changes (REQ-RUL-002)."""

    EQ = "eq"
    NE = "ne"
    IN = "in"
    NOT_IN = "not_in"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"
    CHANGED = "changed"
    CHANGED_FROM = "changed_from"
    CHANGED_TO = "changed_to"


class FieldKind(StrEnum):
    """What a rule field holds; decides its operators and how values are checked."""

    TEXT = "text"
    CODE = "code"  # one of a known set (status, priority, channel, a custom choice)
    REFERENCE = "reference"  # the ID of a group, person, site, category ...
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    CODES = "codes"  # a list of codes (tags, multiple choice)


class ActionMode(StrEnum):
    """Whether a set action may replace what a person entered (REQ-RUL-003)."""

    FILL_EMPTY = "fill_empty"
    OVERWRITE = "overwrite"


_COMPARE = {RuleOp.EQ, RuleOp.NE, RuleOp.IN, RuleOp.NOT_IN, RuleOp.IS_NULL, RuleOp.IS_NOT_NULL}
_CHANGE = {RuleOp.CHANGED, RuleOp.CHANGED_FROM, RuleOp.CHANGED_TO}
_ORDERED = {RuleOp.GT, RuleOp.GTE, RuleOp.LT, RuleOp.LTE}
OPERATORS: Mapping[FieldKind, frozenset[RuleOp]] = {
    FieldKind.TEXT: frozenset(_COMPARE | _CHANGE | {RuleOp.CONTAINS, RuleOp.STARTS_WITH}),
    FieldKind.CODE: frozenset(_COMPARE | _CHANGE),
    FieldKind.REFERENCE: frozenset(_COMPARE | _CHANGE),
    FieldKind.NUMBER: frozenset(_COMPARE | _CHANGE | _ORDERED),
    FieldKind.BOOLEAN: frozenset({RuleOp.EQ, RuleOp.NE, RuleOp.CHANGED, RuleOp.CHANGED_TO}),
    FieldKind.DATETIME: frozenset(_COMPARE | _ORDERED | {RuleOp.CHANGED}),
    FieldKind.CODES: frozenset(_COMPARE | _CHANGE | {RuleOp.CONTAINS}),
}
_NO_VALUE = {RuleOp.IS_NULL, RuleOp.IS_NOT_NULL, RuleOp.CHANGED}
_LIST = {RuleOp.IN, RuleOp.NOT_IN}


@dataclass(frozen=True)
class RuleField:
    """One field rules may test, and whether (and how) they may set it."""

    kind: FieldKind
    values: frozenset[str] | None = None  # allowed codes (CODE, CODES); None: any
    settable: bool = False
    # Read-only facts about related records (requester.vip): never set by a rule.
    derived: bool = False


Problem = tuple[str, str, dict[str, Any]]  # (path, code, params)


@dataclass(frozen=True)
class RuleAction:
    """Set a field (fill empty or overwrite) or refuse the save with a message."""

    kind: str  # "set" | "refuse"
    field: str | None = None
    value: JsonValue = None
    mode: ActionMode = ActionMode.FILL_EMPTY
    message: Mapping[str, str] = dataclasses.field(default_factory=dict)


@dataclass(frozen=True)
class RuleDef:
    """A business rule as the engine runs it (enabled ones only, in order)."""

    id: str
    name: str
    events: frozenset[RuleEvent]
    conditions: Mapping[str, Any] | None
    actions: tuple[RuleAction, ...]
    stop_after: bool = False
    site_id: str | None = None


@dataclass
class TraceLine:
    """What one rule did on one save: shown on the record and kept in the run log."""

    rule_id: str
    rule: str
    outcome: str  # applied | no_match | refused | stopped_before | site_excluded | not_this_event
    changes: dict[str, tuple[JsonValue, JsonValue]] = dataclasses.field(default_factory=dict)
    kept: list[str] = dataclasses.field(
        default_factory=list
    )  # fill-empty actions that left a value alone
    stopped: bool = False


@dataclass
class Refusal:
    """The save is refused with the rule's message (REQ-RUL-004)."""

    rule_id: str
    rule: str
    message: Mapping[str, str]


@dataclass
class RulesOutcome:
    """Every change the rules made (field → value, with the rule that made it last)."""

    values: dict[str, JsonValue] = dataclasses.field(default_factory=dict)
    made_by: dict[str, tuple[str, str]] = dataclasses.field(
        default_factory=dict
    )  # field → (id, name)
    trace: list[TraceLine] = dataclasses.field(default_factory=list)
    refusal: Refusal | None = None


# --- checks when a rule is saved (REQ-RUL-029) ---------------------------------------------------


def _field_for(name: str, fields: Mapping[str, RuleField]) -> RuleField | None:
    return fields.get(name)


def check_conditions(  # noqa: C901, PLR0911, PLR0912 - one rule per node shape and operator, flat
    node: Any,  # noqa: ANN401 - untrusted JSON
    fields: Mapping[str, RuleField],
    path: str = "conditions",
    depth: int = 0,
    counter: list[int] | None = None,
) -> list[Problem]:
    """Problems with a condition tree: unknown fields, operators or values, too big."""
    counter = counter if counter is not None else [0]
    if depth > MAX_DEPTH:
        return [(path, "filter_too_deep", {"max": MAX_DEPTH})]
    if not isinstance(node, dict) or not node:
        return [(path, "invalid_node", {})]
    for group in ("and", "or"):
        if group in node:
            items = node[group]
            if set(node) != {group} or not isinstance(items, list) or not items:
                return [(path, "invalid_group", {})]
            found: list[Problem] = []
            for index, item in enumerate(items):
                found += check_conditions(
                    item, fields, f"{path}.{group}.{index}", depth + 1, counter
                )
            return found
    counter[0] += 1
    if counter[0] > MAX_CONDITIONS:
        return [(path, "too_many_conditions", {"max": MAX_CONDITIONS})]
    name, op, value = node.get("field"), node.get("op"), node.get("value")
    if set(node) - {"field", "op", "value"}:
        return [(path, "invalid_node", {})]
    if not isinstance(name, str):
        return [(f"{path}.field", "unknown_field", {})]
    spec = _field_for(name, fields)
    if spec is None:
        return [(f"{path}.field", "unknown_field", {"field": name})]
    try:
        operator = RuleOp(str(op))
    except ValueError:
        return [(f"{path}.op", "unknown_operator", {"op": str(op)})]
    if operator not in OPERATORS[spec.kind]:
        return [(f"{path}.op", "operator_not_allowed", {"field": name, "op": operator.value})]
    if operator in _NO_VALUE:
        return [] if value is None else [(f"{path}.value", "invalid_value", {"field": name})]
    if operator in _LIST and (not isinstance(value, list) or not value):
        return [(f"{path}.value", "invalid_value", {"field": name})]
    values: list[JsonValue] = value if isinstance(value, list) and operator in _LIST else [value]
    problems: list[Problem] = []
    for item in values:
        problem = check_value(spec, item)
        if problem is not None:
            problems.append((f"{path}.value", problem, {"field": name}))
    return problems


def check_value(spec: RuleField, value: JsonValue) -> str | None:  # noqa: PLR0911 - one return per kind
    """A problem code when `value` cannot be a value of the field, else None."""
    if value is None:
        return None
    if spec.kind in {FieldKind.TEXT, FieldKind.REFERENCE, FieldKind.DATETIME}:
        return None if isinstance(value, str) and len(value) <= NAME_MAX * 5 else "invalid_value"
    if spec.kind == FieldKind.NUMBER:
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        return None if ok else "invalid_value"
    if spec.kind == FieldKind.BOOLEAN:
        return None if isinstance(value, bool) else "invalid_value"
    if spec.kind == FieldKind.CODES and isinstance(value, list):
        bad = [v for v in value if not isinstance(v, str)]
        if bad:
            return "invalid_value"
        if spec.values is not None and not set(value) <= spec.values:
            return "invalid_choice"
        return None
    if not isinstance(value, str):
        return "invalid_value"
    if spec.values is not None and value not in spec.values:
        return "invalid_choice"
    return None


def check_actions(actions: Any, fields: Mapping[str, RuleField]) -> list[Problem]:  # noqa: ANN401, C901, PLR0912 - untrusted JSON; one rule per action shape
    """Problems with a rule's actions: unknown or read-only fields, bad values, empty refusal."""
    if not isinstance(actions, list) or not actions:
        return [("actions", "required", {})]
    if len(actions) > MAX_ACTIONS:
        return [("actions", "too_many_actions", {"max": MAX_ACTIONS})]
    problems: list[Problem] = []
    seen: set[str] = set()
    for index, action in enumerate(actions):
        path = f"actions.{index}"
        if not isinstance(action, dict):
            problems.append((path, "invalid_node", {}))
            continue
        kind = action.get("kind")
        if kind == "refuse":
            message = action.get("message")
            if not isinstance(message, dict) or not str(message.get("en", "")).strip():
                problems.append((f"{path}.message", "message_required", {}))
            elif any(len(str(text)) > MAX_MESSAGE for text in message.values()):
                problems.append((f"{path}.message", "value_too_long", {"max_length": MAX_MESSAGE}))
            elif set(message) - set(LANGUAGES):
                problems.append((f"{path}.message", "invalid_choice", {}))
            continue
        if kind != "set":
            problems.append((f"{path}.kind", "invalid_choice", {}))
            continue
        name = action.get("field")
        spec = fields.get(name) if isinstance(name, str) else None
        if not isinstance(name, str) or spec is None or not spec.settable:
            problems.append((f"{path}.field", "field_not_settable", {"field": str(name)}))
            continue
        if name in seen:
            problems.append((f"{path}.field", "field_set_twice", {"field": name}))
            continue
        seen.add(name)
        try:
            ActionMode(action.get("mode", ActionMode.FILL_EMPTY))
        except ValueError:
            problems.append((f"{path}.mode", "invalid_choice", {}))
        problem = check_value(spec, action.get("value"))
        if problem is not None:
            problems.append((f"{path}.value", problem, {"field": name}))
    return problems


def custom_field_name(name: str) -> bool:
    """`custom.<key>`: a custom field of the record (WP-026)."""
    return bool(_CUSTOM.fullmatch(name))


# --- running -------------------------------------------------------------------------------------


def _empty(value: JsonValue) -> bool:
    return value is None or value in ("", [])


def _compare(op: RuleOp, current: JsonValue, value: JsonValue) -> bool:  # noqa: C901, PLR0911, PLR0912 - one branch per operator
    if op == RuleOp.IS_NULL:
        return _empty(current)
    if op == RuleOp.IS_NOT_NULL:
        return not _empty(current)
    if isinstance(current, list):  # a list of codes: eq/in mean "includes", ne/not_in "excludes"
        wanted = value if isinstance(value, list) else [value]
        includes = any(item in current for item in wanted)
        if op in {RuleOp.EQ, RuleOp.IN, RuleOp.CONTAINS}:
            return includes
        if op in {RuleOp.NE, RuleOp.NOT_IN}:
            return not includes
        return False
    if op == RuleOp.EQ:
        return bool(current == value)
    if op == RuleOp.NE:
        return bool(current != value)
    if op == RuleOp.IN:
        return current in value
    if op == RuleOp.NOT_IN:
        return current not in value
    if op == RuleOp.CONTAINS:
        return isinstance(current, str) and str(value).casefold() in current.casefold()
    if op == RuleOp.STARTS_WITH:
        return isinstance(current, str) and current.casefold().startswith(str(value).casefold())
    if current is None or value is None:
        return False
    try:
        if op == RuleOp.GT:
            return bool(current > value)
        if op == RuleOp.GTE:
            return bool(current >= value)
        if op == RuleOp.LT:
            return bool(current < value)
        return bool(current <= value)
    except TypeError:
        return False


def matches(  # noqa: PLR0911 - one return per operator family
    node: Mapping[str, Any] | None,
    before: Mapping[str, JsonValue] | None,
    after: Mapping[str, JsonValue],
) -> bool:
    """Whether the record (after the save so far) meets the conditions; None matches all."""
    if node is None:
        return True
    if "and" in node:
        return all(matches(item, before, after) for item in node["and"])
    if "or" in node:
        return any(matches(item, before, after) for item in node["or"])
    name, op, value = node["field"], RuleOp(node["op"]), node.get("value")
    current = after.get(name)
    if op in _CHANGE:
        if before is None:  # a new record: nothing changed "from" anything
            return op == RuleOp.CHANGED_TO and current == value
        previous = before.get(name)
        if previous == current:
            return False
        if op == RuleOp.CHANGED:
            return True
        return previous == value if op == RuleOp.CHANGED_FROM else current == value
    return _compare(op, current, value)


def run_rules(  # noqa: C901 - one step per outcome of a rule, flat
    rules: Sequence[RuleDef],
    event: RuleEvent,
    before: Mapping[str, JsonValue] | None,
    after: Mapping[str, JsonValue],
) -> RulesOutcome:
    """Run the enabled rules in order on one save (REQ-RUL-001..005).

    Each rule sees what earlier rules changed. A refusal ends the run at once; "stop after this
    rule" ends it when the rule matches, and every later rule is traced as not run, with why.
    """
    outcome = RulesOutcome()
    current = dict(after)
    stopped_by: str | None = None
    for rule in rules:
        if stopped_by is not None:
            outcome.trace.append(TraceLine(rule.id, rule.name, "stopped_before"))
            continue
        if event not in rule.events:
            continue
        if rule.site_id is not None and current.get("site_id") != rule.site_id:
            continue
        if not matches(rule.conditions, before, current):
            outcome.trace.append(TraceLine(rule.id, rule.name, "no_match"))
            continue
        line = TraceLine(rule.id, rule.name, "applied", stopped=rule.stop_after)
        for action in rule.actions:
            if action.kind == "refuse":
                outcome.refusal = Refusal(rule.id, rule.name, dict(action.message))
                line.outcome = "refused"
                outcome.trace.append(line)
                return outcome
            name = action.field or ""
            existing = current.get(name)
            if action.mode == ActionMode.FILL_EMPTY and not _empty(existing):
                line.kept.append(name)
                continue
            if existing == action.value:
                continue
            line.changes[name] = (existing, action.value)
            current[name] = action.value
            outcome.values[name] = action.value
            outcome.made_by[name] = (rule.id, rule.name)
        outcome.trace.append(line)
        if rule.stop_after:
            stopped_by = rule.id
    return outcome


def message_for(message: Mapping[str, str], locale: str) -> str:
    """The refusal in the user's language, else English."""
    text = message.get(locale) or message.get("en") or ""
    return text.strip()
