"""Visual workflow definitions and their validation (WP-048b, ADR-043 §1-2). Pure: no I/O.

Requirements: REQ-WF-008, 009, 011, 012, 013, 018, 019, 029.

A definition is data: `{"format": 1, "nodes": [...], "links": [...], "variables": [...]}`. A node
is `{id, type, config, position}`; a link joins one named output (`port`) of a node to another
node. Node types are a closed registry: each declares its outputs, how its config is checked and
which record types it is offered for. Validation names every problem with the node or link it is
about, so the designer can select it; drafts save with problems, only a clean version publishes.

Conditions (if, switch, wait) are the business rules' grammar (`rules.check_conditions`), so a
workflow and a rule read a record the same way. A workflow's own variables are typed (text,
number, yes/no, date and time) and conditions read them as `var.<name>` (REQ-WF-016, S2).

Command nodes (set status, field update, note, sub-flow) may retry a failed command a few times
before taking their error output (REQ-WF-024, S2). A sub-flow starts another workflow on the same
record and waits for it to finish; recursion is refused on save by the service (REQ-WF-017).
"""

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.modules.automation.domain.rules import (
    FieldKind,
    JsonValue,
    RuleField,
    check_conditions,
    check_value,
)

FORMAT = 1
MAX_NODES = 200  # Appendix A
MAX_LOOP_ROUNDS = 100  # Appendix A: a loop runs at most 100 rounds
MAX_STEPS = 10_000  # Appendix A: steps per instance
MAX_LINKS = 600
MAX_SWITCH_CASES = 20
MAX_BRANCHES = 10
MIN_BRANCHES = 2
MAX_VARIABLES = 50
MAX_WAIT_SECONDS = 366 * 24 * 3600  # a wait's limit or a timer: at most a year
ID_MAX = 40
NOTE_MAX = 5000
VARIABLE_TEXT_MAX = 1000
MAX_RETRIES = 5
RETRY_SECONDS_MIN = 10
RETRY_SECONDS_MAX = 24 * 3600
VAR_PREFIX = "var."  # how conditions name a variable: var.<name>
VARIABLE_KINDS = frozenset(
    {FieldKind.TEXT, FieldKind.NUMBER, FieldKind.BOOLEAN, FieldKind.DATETIME}
)

# (where, code, params): `where` is "node:<id>", "link:<index>" or "definition".
Problem = tuple[str, str, dict[str, JsonValue]]


class Category(StrEnum):
    """The palette's groups, shown with text, never only an icon (REQ-WF-028)."""

    FLOW = "flow"
    LOGIC = "logic"
    PEOPLE = "people"
    ACTIONS = "actions"
    STRUCTURE = "structure"


class NodeType(StrEnum):
    """The node registry's types (ADR-043 §2); people and outside actions join in S2."""

    START = "start"
    END = "end"
    SET_STATUS = "set_status"
    IF = "if"
    SWITCH = "switch"
    WAIT = "wait"
    TIMER = "timer"
    FIELD_UPDATE = "field_update"
    NOTE = "note"
    SPLIT = "split"
    JOIN = "join"
    SET_VARIABLE = "set_variable"
    SUB_FLOW = "sub_flow"


class WaitEvent(StrEnum):
    """What a wait node can listen for on its record (REQ-WF-012)."""

    FIELD_CHANGED = "field_changed"
    STATUS_CHANGED = "status_changed"
    NOTE_ADDED = "note_added"
    REQUESTER_REPLIED = "requester_replied"
    APPROVAL_DECIDED = "approval_decided"
    TASK_COMPLETED = "task_completed"
    WORKLOG_ADDED = "worklog_added"


class JoinMode(StrEnum):
    """How a join continues (REQ-WF-018)."""

    ALL = "all"
    FIRST = "first"
    COUNT = "count"


class TimeBasis(StrEnum):
    """Timers and wait limits count calendar or business time (REQ-WF-013)."""

    CALENDAR = "calendar"
    BUSINESS = "business"


@dataclass(frozen=True)
class Node:
    """One node: its type, its config and where it sits on the canvas."""

    id: str
    type: NodeType
    config: Mapping[str, Any]
    position: tuple[float, float]


@dataclass(frozen=True)
class Link:
    """One output (`port`) of a node joined to another node."""

    source: str
    port: str
    target: str


@dataclass(frozen=True)
class Variable:
    """A workflow variable: its name and what it holds."""

    name: str
    kind: FieldKind = FieldKind.TEXT


@dataclass(frozen=True)
class Definition:
    """A whole workflow as the interpreter and the designer read it."""

    nodes: tuple[Node, ...]
    links: tuple[Link, ...]
    variables: tuple[Variable, ...] = ()

    def node(self, node_id: str) -> Node:
        """The node with this ID (validated definitions only)."""
        return next(n for n in self.nodes if n.id == node_id)

    def next_of(self, node_id: str, port: str) -> str | None:
        """The node an output leads to; None when the output is not linked."""
        return next((x.target for x in self.links if x.source == node_id and x.port == port), None)

    def incoming(self, node_id: str) -> tuple[Link, ...]:
        """The links into a node."""
        return tuple(x for x in self.links if x.target == node_id)

    def to_json(self) -> dict[str, Any]:
        """The stored form; re-reading it gives the same diagram (REQ-WF-008 AC3)."""
        return {
            "format": FORMAT,
            "nodes": [
                {
                    "id": n.id,
                    "type": n.type.value,
                    "config": dict(n.config),
                    "position": {"x": n.position[0], "y": n.position[1]},
                }
                for n in self.nodes
            ],
            "links": [{"from": x.source, "port": x.port, "to": x.target} for x in self.links],
            "variables": [{"name": v.name, "kind": v.kind.value} for v in self.variables],
        }


@dataclass(frozen=True)
class TypeFacts:
    """What validation knows about the workflow's record type, from its owning module."""

    record_type: str
    fields: Mapping[str, RuleField]  # what conditions may test (the rules' catalogue)
    settable: frozenset[str]  # what a field update may set (the edit form's fields)
    actions: frozenset[str]  # status moves by action code a workflow may run
    system_actions: frozenset[str] = frozenset()  # system-only: refused at design time
    date_fields: frozenset[str] = frozenset()  # what a timer may count to


@dataclass(frozen=True)
class NodeSpec:
    """What the registry knows about one node type."""

    type: NodeType
    category: Category
    # The outputs of a node with this config, and those it may leave unlinked.
    outputs: Callable[[Mapping[str, Any]], tuple[str, ...]]
    optional: Callable[[Mapping[str, Any]], frozenset[str]]
    check: Callable[[Mapping[str, Any], TypeFacts], list[tuple[str, dict[str, JsonValue]]]]
    record_types: frozenset[str] | None = None  # None: offered for every type


def _fixed(*ports: str) -> Callable[[Mapping[str, Any]], tuple[str, ...]]:
    return lambda _config: ports


def _none(_config: Mapping[str, Any]) -> frozenset[str]:
    return frozenset()


def _ok(_config: Mapping[str, Any], _facts: TypeFacts) -> list[tuple[str, dict[str, JsonValue]]]:
    return []


def _conditions(node: Any, facts: TypeFacts) -> list[tuple[str, dict[str, JsonValue]]]:  # noqa: ANN401 - untrusted JSON
    return [(code, params) for _path, code, params in check_conditions(node, facts.fields)]


def _seconds(value: Any) -> bool:  # noqa: ANN401 - untrusted JSON
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= MAX_WAIT_SECONDS


def _rounds(config: Mapping[str, Any]) -> list[tuple[str, dict[str, JsonValue]]]:
    rounds = config.get("max_rounds")
    if rounds is None:
        return []
    if (
        not isinstance(rounds, int)
        or isinstance(rounds, bool)
        or not 1 <= rounds <= MAX_LOOP_ROUNDS
    ):
        return [("loop_limit_invalid", {"max": MAX_LOOP_ROUNDS})]
    return []


def _check_set_status(
    config: Mapping[str, Any], facts: TypeFacts
) -> list[tuple[str, dict[str, JsonValue]]]:
    action = config.get("action")
    if action in facts.system_actions:
        return [("system_status_not_allowed", {"action": str(action)})]
    if not isinstance(action, str) or action not in facts.actions:
        return [("unknown_action", {"action": str(action)})]
    return _retries(config)


def _check_if(
    config: Mapping[str, Any], facts: TypeFacts
) -> list[tuple[str, dict[str, JsonValue]]]:
    return _conditions(config.get("condition"), facts) + _rounds(config)


def _switch_ports(config: Mapping[str, Any]) -> tuple[str, ...]:
    cases = config.get("cases")
    ports = (
        [str(c.get("port")) for c in cases if isinstance(c, dict)]
        if isinstance(cases, list)
        else []
    )
    return (*ports, "default")


def _check_switch(
    config: Mapping[str, Any], facts: TypeFacts
) -> list[tuple[str, dict[str, JsonValue]]]:
    cases = config.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_SWITCH_CASES:
        return [("switch_cases_invalid", {"max": MAX_SWITCH_CASES})]
    problems: list[tuple[str, dict[str, JsonValue]]] = []
    seen: set[str] = set()
    for case in cases:
        port = case.get("port") if isinstance(case, dict) else None
        if not isinstance(port, str) or not _valid_id(port) or port == "default" or port in seen:
            problems.append(("switch_case_invalid", {"port": str(port)}))
            continue
        seen.add(port)
        problems += _conditions(case.get("condition"), facts)
    return problems + _rounds(config)


def _wait_ports(config: Mapping[str, Any]) -> tuple[str, ...]:
    return ("next", "overtaken", *(("timeout",) if config.get("limit_seconds") else ()))


def _check_wait(
    config: Mapping[str, Any], facts: TypeFacts
) -> list[tuple[str, dict[str, JsonValue]]]:
    events = config.get("events")
    problems: list[tuple[str, dict[str, JsonValue]]] = []
    valid = {e.value for e in WaitEvent}
    if not isinstance(events, list) or any(e not in valid for e in events):
        problems.append(("wait_events_invalid", {}))
        events = []
    limit = config.get("limit_seconds")
    if limit is not None and not _seconds(limit):
        problems.append(("duration_invalid", {"max": MAX_WAIT_SECONDS}))
    if not events and limit is None:
        problems.append(("wait_never_finishes", {}))  # REQ-WF-019
    for key in ("condition", "overtaken_when"):
        if config.get(key) is not None:
            problems += _conditions(config[key], facts)
    if config.get("basis", TimeBasis.CALENDAR.value) not in {b.value for b in TimeBasis}:
        problems.append(("time_basis_invalid", {}))
    return problems + _rounds(config)


def _check_timer(
    config: Mapping[str, Any], facts: TypeFacts
) -> list[tuple[str, dict[str, JsonValue]]]:
    seconds, until = config.get("seconds"), config.get("until_field")
    if (seconds is None) == (until is None):
        return [("timer_needs_duration_or_date", {})]
    if seconds is not None and not _seconds(seconds):
        return [("duration_invalid", {"max": MAX_WAIT_SECONDS})]
    if until is not None:
        if until not in facts.date_fields:
            return [("unknown_field", {"field": str(until)})]
        offset = config.get("offset_seconds", 0)
        if (
            not isinstance(offset, int)
            or isinstance(offset, bool)
            or abs(offset) > MAX_WAIT_SECONDS
        ):
            return [("duration_invalid", {"max": MAX_WAIT_SECONDS})]
    if config.get("basis", TimeBasis.CALENDAR.value) not in {b.value for b in TimeBasis}:
        return [("time_basis_invalid", {})]
    return []


def _retries(config: Mapping[str, Any]) -> list[tuple[str, dict[str, JsonValue]]]:
    """A command node's retries: none, or up to five, a while apart (REQ-WF-024)."""
    retries, wait = config.get("retries", 0), config.get("retry_seconds", 60)
    if not _whole(retries) or not 0 <= retries <= MAX_RETRIES:
        return [("retries_invalid", {"max": MAX_RETRIES})]
    if not _whole(wait) or not RETRY_SECONDS_MIN <= wait <= RETRY_SECONDS_MAX:
        return [("retry_wait_invalid", {"min": RETRY_SECONDS_MIN, "max": RETRY_SECONDS_MAX})]
    return []


def _whole(value: Any) -> bool:  # noqa: ANN401 - untrusted JSON
    return isinstance(value, int) and not isinstance(value, bool)


def _check_field_update(
    config: Mapping[str, Any], facts: TypeFacts
) -> list[tuple[str, dict[str, JsonValue]]]:
    return _field_values(config, facts) + _retries(config)


def _field_values(
    config: Mapping[str, Any], facts: TypeFacts
) -> list[tuple[str, dict[str, JsonValue]]]:
    values = config.get("values")
    if not isinstance(values, dict) or not values:
        return [("field_update_empty", {})]
    problems: list[tuple[str, dict[str, JsonValue]]] = []
    for name, value in values.items():
        spec = facts.fields.get(name)
        if name not in facts.settable or spec is None:
            problems.append(("field_not_settable", {"field": str(name)}))  # REQ-WF-015 AC2
            continue
        problem = check_value(spec, value)
        if problem is not None:
            problems.append((problem, {"field": str(name)}))
    return problems


def _check_note(
    config: Mapping[str, Any], _facts: TypeFacts
) -> list[tuple[str, dict[str, JsonValue]]]:
    text = config.get("text")
    if (
        not isinstance(text, dict)
        or not text
        or not all(isinstance(v, str) and 0 < len(v) <= NOTE_MAX for v in text.values())
    ):
        return [("note_text_invalid", {"max": NOTE_MAX})]
    if not isinstance(config.get("private", True), bool):
        return [("invalid_value", {"field": "private"})]
    return _retries(config)


def variable_value_problem(kind: FieldKind, value: Any) -> str | None:  # noqa: ANN401 - untrusted JSON
    """Why `value` cannot be held by a variable of `kind`, or None."""
    if value is None:
        return None  # cleared
    match kind:
        case FieldKind.NUMBER:
            ok = isinstance(value, int | float) and not isinstance(value, bool)
        case FieldKind.BOOLEAN:
            ok = isinstance(value, bool)
        case FieldKind.DATETIME:
            ok = isinstance(value, str) and _iso(value)
        case _:
            ok = isinstance(value, str) and len(value) <= VARIABLE_TEXT_MAX
    return None if ok else "variable_value_invalid"


def _iso(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _check_set_variable(
    config: Mapping[str, Any], facts: TypeFacts
) -> list[tuple[str, dict[str, JsonValue]]]:
    """Set a declared variable to a fixed value, or to a field of the record."""
    name = config.get("variable")
    spec = facts.fields.get(f"{VAR_PREFIX}{name}") if isinstance(name, str) else None
    if spec is None:
        return [("variable_unknown", {"variable": str(name)})]
    source = config.get("from_field")
    if source is not None:
        found = facts.fields.get(str(source)) if not str(source).startswith(VAR_PREFIX) else None
        if found is None:
            return [("unknown_field", {"field": str(source)})]
        return []
    problem = variable_value_problem(spec.kind, config.get("value"))
    return [(problem, {"variable": name})] if problem else []


def _check_sub_flow(
    config: Mapping[str, Any], _facts: TypeFacts
) -> list[tuple[str, dict[str, JsonValue]]]:
    """Which workflow to run; whether it may (same type, no recursion) is the service's check."""
    try:
        uuid.UUID(str(config.get("workflow_id")))
    except ValueError:
        return [("sub_flow_workflow_missing", {})]
    return _retries(config)


def _split_ports(config: Mapping[str, Any]) -> tuple[str, ...]:
    branches = config.get("branches")
    return tuple(str(b) for b in branches) if isinstance(branches, list) else ()


def _check_split(
    config: Mapping[str, Any], _facts: TypeFacts
) -> list[tuple[str, dict[str, JsonValue]]]:
    branches = config.get("branches")
    if (
        not isinstance(branches, list)
        or not MIN_BRANCHES <= len(branches) <= MAX_BRANCHES
        or len(set(map(str, branches))) != len(branches)
        or not all(isinstance(b, str) and _valid_id(b) for b in branches)
    ):
        return [("split_branches_invalid", {"max": MAX_BRANCHES})]
    return []


def _check_join(
    config: Mapping[str, Any], _facts: TypeFacts
) -> list[tuple[str, dict[str, JsonValue]]]:
    mode = config.get("mode", JoinMode.ALL.value)
    if mode not in {m.value for m in JoinMode}:
        return [("join_mode_invalid", {})]
    if mode == JoinMode.COUNT.value:
        count = config.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_BRANCHES:
            return [("join_count_invalid", {"max": MAX_BRANCHES})]
    return []


REGISTRY: Mapping[NodeType, NodeSpec] = {
    NodeType.START: NodeSpec(NodeType.START, Category.FLOW, _fixed("next"), _none, _ok),
    NodeType.END: NodeSpec(NodeType.END, Category.FLOW, _fixed(), _none, _ok),
    NodeType.SET_STATUS: NodeSpec(
        NodeType.SET_STATUS,
        Category.FLOW,
        _fixed("next", "error"),
        lambda _c: frozenset({"error"}),
        _check_set_status,
    ),
    NodeType.IF: NodeSpec(NodeType.IF, Category.LOGIC, _fixed("yes", "no"), _none, _check_if),
    NodeType.SWITCH: NodeSpec(NodeType.SWITCH, Category.LOGIC, _switch_ports, _none, _check_switch),
    NodeType.WAIT: NodeSpec(NodeType.WAIT, Category.LOGIC, _wait_ports, _none, _check_wait),
    NodeType.TIMER: NodeSpec(NodeType.TIMER, Category.LOGIC, _fixed("next"), _none, _check_timer),
    NodeType.FIELD_UPDATE: NodeSpec(
        NodeType.FIELD_UPDATE,
        Category.ACTIONS,
        _fixed("next", "error"),
        lambda _c: frozenset({"error"}),
        _check_field_update,
    ),
    NodeType.NOTE: NodeSpec(
        NodeType.NOTE,
        Category.ACTIONS,
        _fixed("next", "error"),
        lambda _c: frozenset({"error"}),
        _check_note,
    ),
    NodeType.SPLIT: NodeSpec(NodeType.SPLIT, Category.STRUCTURE, _split_ports, _none, _check_split),
    NodeType.JOIN: NodeSpec(NodeType.JOIN, Category.STRUCTURE, _fixed("next"), _none, _check_join),
    NodeType.SET_VARIABLE: NodeSpec(
        NodeType.SET_VARIABLE, Category.LOGIC, _fixed("next"), _none, _check_set_variable
    ),
    NodeType.SUB_FLOW: NodeSpec(
        NodeType.SUB_FLOW,
        Category.STRUCTURE,
        _fixed("next", "error"),
        lambda _c: frozenset({"error"}),
        _check_sub_flow,
    ),
}


def sub_flows(definition: Definition) -> dict[str, uuid.UUID]:
    """The workflows a definition's sub-flow nodes start, by node (for the recursion check)."""
    found: dict[str, uuid.UUID] = {}
    for node in definition.nodes:
        if node.type != NodeType.SUB_FLOW:
            continue
        try:
            found[node.id] = uuid.UUID(str(node.config.get("workflow_id")))
        except ValueError:
            continue
    return found


def with_variables(facts: TypeFacts, variables: Sequence[Variable]) -> TypeFacts:
    """The facts conditions and nodes see: the record's fields plus `var.<name>` for each one."""
    extra = {f"{VAR_PREFIX}{v.name}": RuleField(v.kind) for v in variables}
    return replace(facts, fields={**facts.fields, **extra})


def offered(record_type: str) -> tuple[NodeType, ...]:
    """The node types the designer offers for a record type (REQ-WF-009 AC3)."""
    return tuple(
        t
        for t, spec in REGISTRY.items()
        if spec.record_types is None or record_type in spec.record_types
    )


def _valid_id(value: str) -> bool:
    return 0 < len(value) <= ID_MAX and value.replace("_", "").replace("-", "").isalnum()


@dataclass
class Parsed:
    """A read definition, or None, with the problems found while reading it."""

    definition: Definition | None
    problems: list[Problem] = field(default_factory=list)


def parse(raw: Any) -> Parsed:  # noqa: ANN401, C901, PLR0912 - untrusted JSON, one check per shape
    """The definition from its JSON, or the problems that keep it from being read at all."""
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        return Parsed(None, [("definition", "definition_format_invalid", {"format": FORMAT})])
    nodes_raw, links_raw = raw.get("nodes"), raw.get("links", [])
    variables_raw = raw.get("variables", [])
    if not isinstance(nodes_raw, list) or not isinstance(links_raw, list):
        return Parsed(None, [("definition", "definition_shape_invalid", {})])
    if len(nodes_raw) > MAX_NODES:
        return Parsed(None, [("definition", "too_many_nodes", {"max": MAX_NODES})])  # REQ-WF-029
    if len(links_raw) > MAX_LINKS:
        return Parsed(None, [("definition", "too_many_links", {"max": MAX_LINKS})])
    variables = _variables(variables_raw)
    if variables is None:
        return Parsed(None, [("definition", "variables_invalid", {"max": MAX_VARIABLES})])
    nodes: list[Node] = []
    problems: list[Problem] = []
    seen: set[str] = set()
    for index, item in enumerate(nodes_raw):
        where = f"node:{item.get('id')}" if isinstance(item, dict) else f"node:#{index}"
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            problems.append((where, "node_invalid", {}))
            continue
        node_id = item["id"]
        if not _valid_id(node_id) or node_id in seen:
            problems.append((where, "node_id_invalid", {"id": node_id}))
            continue
        seen.add(node_id)
        try:
            node_type = NodeType(str(item.get("type")))
        except ValueError:
            problems.append((where, "unknown_node_type", {"type": str(item.get("type"))}))
            continue
        config = item.get("config", {})
        position = item.get("position", {})
        if not isinstance(config, dict) or not isinstance(position, dict):
            problems.append((where, "node_invalid", {}))
            continue
        x, y = position.get("x", 0), position.get("y", 0)
        if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in (x, y)):
            problems.append((where, "node_invalid", {}))
            continue
        nodes.append(Node(node_id, node_type, config, (float(x), float(y))))
    links: list[Link] = []
    for index, item in enumerate(links_raw):
        if not isinstance(item, dict) or not all(
            isinstance(item.get(k), str) for k in ("from", "port", "to")
        ):
            problems.append((f"link:{index}", "link_invalid", {}))
            continue
        links.append(Link(item["from"], item["port"], item["to"]))
    return Parsed(Definition(tuple(nodes), tuple(links), variables), problems)


def _variables(raw: Any) -> tuple[Variable, ...] | None:  # noqa: ANN401 - untrusted JSON
    """Variables as names (format 1 from S1: text) or {name, kind}; None when unreadable."""
    if not isinstance(raw, list) or len(raw) > MAX_VARIABLES:
        return None
    found: list[Variable] = []
    for item in raw:
        name, kind = (item, FieldKind.TEXT.value) if isinstance(item, str) else (None, None)
        if isinstance(item, dict):
            name, kind = item.get("name"), item.get("kind", FieldKind.TEXT.value)
        if not isinstance(name, str) or not _valid_id(name) or kind not in VARIABLE_KINDS:
            return None
        if any(v.name == name for v in found):
            return None
        found.append(Variable(name, FieldKind(kind)))
    return tuple(found)


def validate(definition: Definition, facts: TypeFacts) -> list[Problem]:  # noqa: C901 - one check per rule of REQ-WF-019, flat
    """Every problem of a readable definition, each with the node or link it is about."""
    problems: list[Problem] = []
    ids = {n.id for n in definition.nodes}
    allowed = set(offered(facts.record_type))
    facts = with_variables(facts, definition.variables)
    starts = [n for n in definition.nodes if n.type == NodeType.START]
    if len(starts) != 1:
        problems.append(("definition", "one_start_needed", {"found": len(starts)}))
    if not any(n.type == NodeType.END for n in definition.nodes):
        problems.append(("definition", "end_needed", {}))
    for node in definition.nodes:
        where = f"node:{node.id}"
        spec = REGISTRY[node.type]
        if node.type not in allowed:
            problems.append((where, "node_not_for_type", {"type": node.type.value}))
            continue
        problems += [(where, code, params) for code, params in spec.check(node.config, facts)]
    used: set[tuple[str, str]] = set()
    for index, link in enumerate(definition.links):
        where = f"link:{index}"
        if link.source not in ids or link.target not in ids:
            problems.append((where, "link_node_missing", {}))
            continue
        source = definition.node(link.source)
        if link.port not in REGISTRY[source.type].outputs(source.config):
            problems.append((where, "link_port_invalid", {"port": link.port}))
            continue
        if (link.source, link.port) in used:
            problems.append((where, "link_port_twice", {"port": link.port}))
        used.add((link.source, link.port))
        if definition.node(link.target).type == NodeType.START:
            problems.append((where, "link_into_start", {}))
    for node in definition.nodes:
        spec = REGISTRY[node.type]
        optional = spec.optional(node.config)
        for port in spec.outputs(node.config):
            if port not in optional and (node.id, port) not in used:
                problems.append((f"node:{node.id}", "output_not_linked", {"port": port}))
    problems += _reach_problems(definition, starts[0].id if len(starts) == 1 else None)
    problems += _join_problems(definition)
    return problems


def _reach_problems(definition: Definition, start: str | None) -> list[Problem]:
    """Unconnected nodes and nodes with no path to an end (REQ-WF-019 AC1)."""
    forward: dict[str, set[str]] = {n.id: set() for n in definition.nodes}
    backward: dict[str, set[str]] = {n.id: set() for n in definition.nodes}
    for link in definition.links:
        if link.source in forward and link.target in forward:
            forward[link.source].add(link.target)
            backward[link.target].add(link.source)
    reached = _closure([start] if start else [], forward)
    ends = [n.id for n in definition.nodes if n.type == NodeType.END]
    finishing = _closure(ends, backward)
    problems: list[Problem] = []
    for node in definition.nodes:
        if start is not None and node.id not in reached:
            problems.append((f"node:{node.id}", "node_unreachable", {}))
        elif node.id not in finishing:
            problems.append((f"node:{node.id}", "no_path_to_end", {}))
    return problems


def _closure(seeds: Sequence[str], edges: Mapping[str, set[str]]) -> set[str]:
    found, todo = set(seeds), list(seeds)
    while todo:
        for nxt in edges.get(todo.pop(), set()):
            if nxt not in found:
                found.add(nxt)
                todo.append(nxt)
    return found


def _join_problems(definition: Definition) -> list[Problem]:
    """A join needs a split upstream of it (REQ-WF-019)."""
    backward: dict[str, set[str]] = {n.id: set() for n in definition.nodes}
    for link in definition.links:
        if link.target in backward and link.source in backward:
            backward[link.target].add(link.source)
    splits = {n.id for n in definition.nodes if n.type == NodeType.SPLIT}
    return [
        (f"node:{n.id}", "join_without_split", {})
        for n in definition.nodes
        if n.type == NodeType.JOIN and not (_closure([n.id], backward) & splits)
    ]
