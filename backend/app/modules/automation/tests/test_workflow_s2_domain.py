"""Variables, retries and sub-flows (WP-048b S2, ADR-043 §4; REQ-WF-016, -017, -024). No I/O."""

import uuid
from typing import Any

from app.modules.automation.domain.interpreter import (
    CommandDone,
    CommandKind,
    InstanceStatus,
    State,
    TimerFired,
)
from app.modules.automation.domain.rules import FieldKind
from app.modules.automation.domain.workflows import (
    Definition,
    Variable,
    parse,
    sub_flows,
    validate,
)
from app.modules.automation.tests.test_interpreter_domain import NOW, node, step
from app.modules.automation.tests.test_workflows_domain import FACTS, link
from app.modules.automation.tests.test_workflows_domain import node as raw_node

CHILD = str(uuid.uuid4())


def flow(
    nodes: list[dict[str, Any]], links: list[tuple[str, str, str]], variables: list[Any]
) -> Definition:
    parsed = parse(
        {
            "format": 1,
            "nodes": nodes,
            "links": [{"from": a, "port": p, "to": b} for a, p, b in links],
            "variables": variables,
        }
    )
    assert parsed.definition is not None, parsed.problems
    return parsed.definition


def problems(nodes: list[dict[str, Any]], links: list[dict[str, str]], variables: list[Any]) -> Any:  # noqa: ANN401 - the codes
    parsed = parse({"format": 1, "nodes": nodes, "links": links, "variables": variables})
    assert parsed.definition is not None, parsed.problems
    return {(where, code) for where, code, _ in validate(parsed.definition, FACTS)}


def test_req_wf_016_variables_are_typed_and_read_back_and_s1_names_still_read() -> None:
    typed = flow(
        [node("s", "start"), node("e", "end")],
        [("s", "next", "e")],
        ["note", {"name": "tries", "kind": "number"}],
    )
    assert typed.variables == (
        Variable("note", FieldKind.TEXT),
        Variable("tries", FieldKind.NUMBER),
    )
    assert typed.to_json()["variables"] == [
        {"name": "note", "kind": "text"},
        {"name": "tries", "kind": "number"},
    ]
    for bad in (
        [{"name": "x", "kind": "codes"}],  # not a variable kind
        ["x", "x"],  # twice
        [{"name": "bad name"}],
    ):
        unread = parse({"format": 1, "nodes": [], "links": [], "variables": bad})
        assert unread.definition is None
        assert unread.problems[0][1] == "variables_invalid"


def test_req_wf_016_a_variable_is_set_then_read_by_a_condition() -> None:
    definition = flow(
        [
            node("s", "start"),
            node("set", "set_variable", variable="vip", value=True),
            node("copy", "set_variable", variable="was", from_field="priority"),
            node("if", "if", condition={"field": "var.vip", "op": "eq", "value": True}),
            node("yes", "end"),
            node("no", "end"),
        ],
        [
            ("s", "next", "set"),
            ("set", "next", "copy"),
            ("copy", "next", "if"),
            ("if", "yes", "yes"),
            ("if", "no", "no"),
        ],
        [{"name": "vip", "kind": "boolean"}, "was"],
    )
    done = step(definition, State.start(definition), {"priority": "p2"})
    assert done.state.status == InstanceStatus.FINISHED
    assert [s.result for s in done.steps if s.node == "if"] == ["yes"]
    assert done.state.variables == {"vip": True, "was": "p2"}


def test_a_set_variable_is_checked_against_its_kind_and_the_record_s_fields() -> None:
    nodes = [
        raw_node("s", "start"),
        raw_node("a", "set_variable", variable="tries", value="three"),
        raw_node("b", "set_variable", variable="nope", value=1),
        raw_node("c", "set_variable", variable="tries", from_field="missing"),
        raw_node("d", "if", condition={"field": "var.tries", "op": "gt", "value": 2}),
        raw_node("e", "end"),
    ]
    links = [
        link("s", "next", "a"),
        link("a", "next", "b"),
        link("b", "next", "c"),
        link("c", "next", "d"),
        link("d", "yes", "e"),
        link("d", "no", "e"),
    ]
    found = problems(nodes, links, [{"name": "tries", "kind": "number"}])
    assert found == {
        ("node:a", "variable_value_invalid"),
        ("node:b", "variable_unknown"),
        ("node:c", "unknown_field"),
    }  # "d" reads the declared number variable: no problem


def test_req_wf_024_a_failed_command_retries_then_takes_its_error_output() -> None:
    definition = flow(
        [
            node("s", "start"),
            node("mv", "set_status", action="start_progress", retries=2, retry_seconds=30),
            node("ok", "end"),
            node("bad", "end"),
        ],
        [("s", "next", "mv"), ("mv", "next", "ok"), ("mv", "error", "bad")],
        [],
    )
    state = step(definition, State.start(definition))
    for attempt in (1, 2):
        [command] = state.commands
        failed = step(
            definition, state.state, event=CommandDone(command.id, ok=False, error="busy")
        )
        assert failed.commands == []
        assert failed.wake_at is not None
        assert [s.result for s in failed.steps] == ["retry"]
        assert failed.steps[0].detail == {"attempt": attempt, "code": "busy"}
        early = step(definition, failed.state, event=TimerFired(), now=NOW)
        assert early.commands == []  # not due yet
        state = step(definition, failed.state, event=TimerFired(), now=failed.wake_at)
    [last] = state.commands
    gave_up = step(definition, state.state, event=CommandDone(last.id, ok=False, error="busy"))
    assert gave_up.state.status == InstanceStatus.FINISHED
    assert [s.result for s in gave_up.steps if s.node == "mv"] == ["error"]


def test_retries_are_checked() -> None:
    nodes = [
        raw_node("s", "start"),
        raw_node("n", "note", text={"en": "x"}, retries=6),
        raw_node("m", "note", text={"en": "x"}, retries=1, retry_seconds=1),
        raw_node("e", "end"),
    ]
    links = [link("s", "next", "n"), link("n", "next", "m"), link("m", "next", "e")]
    assert problems(nodes, links, []) == {
        ("node:n", "retries_invalid"),
        ("node:m", "retry_wait_invalid"),
    }


def test_req_wf_017_a_sub_flow_is_a_command_whose_end_continues_the_parent() -> None:
    definition = flow(
        [
            node("s", "start"),
            node("child", "sub_flow", workflow_id=CHILD),
            node("e", "end"),
            node("f", "end"),
        ],
        [("s", "next", "child"), ("child", "next", "e"), ("child", "error", "f")],
        [],
    )
    assert sub_flows(definition) == {"child": uuid.UUID(CHILD)}
    started = step(definition, State.start(definition))
    [command] = started.commands
    assert (command.kind, command.payload) == (CommandKind.START_SUB_FLOW, {"workflow_id": CHILD})
    assert started.state.status == InstanceStatus.WAITING
    finished = step(definition, started.state, event=CommandDone(command.id, ok=True))
    assert finished.state.status == InstanceStatus.FINISHED
    failed = step(
        definition, started.state, event=CommandDone(command.id, ok=False, error="sub_flow_failed")
    )
    assert [s.result for s in failed.steps if s.node == "child"] == ["error"]


def test_a_sub_flow_needs_a_workflow() -> None:
    nodes = [raw_node("s", "start"), raw_node("c", "sub_flow"), raw_node("e", "end")]
    links = [link("s", "next", "c"), link("c", "next", "e")]
    assert problems(nodes, links, []) == {("node:c", "sub_flow_workflow_missing")}
