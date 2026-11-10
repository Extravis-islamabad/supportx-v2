"""The approval node (WP-048b S2, REQ-WF-014): opened as a command, its decision picks the output.

No I/O: the interpreter and the validator only.
"""

import uuid
from dataclasses import replace

from app.modules.automation.domain.interpreter import (
    CommandDone,
    CommandKind,
    InstanceStatus,
    State,
)
from app.modules.automation.domain.workflows import (
    REGISTRY,
    Category,
    Definition,
    NodeType,
    TypeFacts,
    parse,
    validate,
)
from app.modules.automation.tests.test_interpreter_domain import node, step
from app.modules.automation.tests.test_workflow_s2_domain import flow
from app.modules.automation.tests.test_workflows_domain import FACTS, link
from app.modules.automation.tests.test_workflows_domain import node as raw_node

PERSON = str(uuid.uuid4())
WITH_APPROVALS = replace(FACTS, approvals=True, roles=frozenset({"release_manager"}))


def _approval_flow() -> Definition:
    return flow(
        [
            node("s", "start"),
            node("ok", "approval", approvers={"user_ids": [PERSON]}, rule="all"),
            node("yes", "end"),
            node("no", "end"),
            node("err", "end"),
        ],
        [
            ("s", "next", "ok"),
            ("ok", "approved", "yes"),
            ("ok", "rejected", "no"),
            ("ok", "error", "err"),
        ],
        [],
    )


def test_req_wf_014_an_approval_waits_and_its_decision_picks_the_output() -> None:
    definition = _approval_flow()
    started = step(definition, State.start(definition))
    [command] = started.commands
    assert command.kind == CommandKind.OPEN_APPROVAL
    assert command.payload == {"approvers": {"user_ids": [PERSON]}, "rule": "all"}
    assert started.state.status == InstanceStatus.WAITING  # until someone decides
    approved = step(
        definition, started.state, event=CommandDone(command.id, ok=True, port="approved")
    )
    assert [s.result for s in approved.steps if s.node == "ok"] == ["approved"]
    assert approved.state.status == InstanceStatus.FINISHED
    rejected = step(
        definition, started.state, event=CommandDone(command.id, ok=True, port="rejected")
    )
    assert [s.result for s in rejected.steps if s.node == "ok"] == ["rejected"]
    refused = step(
        definition, started.state, event=CommandDone(command.id, ok=False, error="no_approver")
    )
    assert [s.result for s in refused.steps if s.node == "ok"] == ["error"]


def test_an_approval_node_is_a_people_node_with_two_outputs_and_an_optional_error() -> None:
    spec = REGISTRY[NodeType.APPROVAL]
    assert spec.category == Category.PEOPLE
    assert spec.outputs({}) == ("approved", "rejected", "error")
    assert spec.optional({}) == frozenset({"error"})


def _problems(config: dict[str, object], facts: TypeFacts = WITH_APPROVALS) -> set[tuple[str, str]]:
    nodes = [
        raw_node("s", "start"),
        raw_node("a", "approval", **config),
        raw_node("y", "end"),
        raw_node("n", "end"),
    ]
    links = [link("s", "next", "a"), link("a", "approved", "y"), link("a", "rejected", "n")]
    parsed = parse({"format": 1, "nodes": nodes, "links": links, "variables": []})
    assert parsed.definition is not None, parsed.problems
    return {(where, code) for where, code, _ in validate(parsed.definition, facts)}


def test_an_approval_names_who_decides_and_how() -> None:
    assert _problems({"approvers": {"user_ids": [PERSON]}}) == set()
    assert _problems({"approvers": {"roles": ["release_manager"]}, "rule": "majority"}) == set()
    assert _problems({}) == {("node:a", "approval_without_approvers")}
    assert _problems({"approvers": {}}) == {("node:a", "approval_without_approvers")}
    assert _problems({"approvers": {"user_ids": ["nope"]}}) == {("node:a", "invalid_value")}
    assert _problems({"approvers": {"roles": ["mayor"]}}) == {("node:a", "approval_role_unknown")}
    assert _problems({"approvers": {"user_ids": [PERSON]}, "rule": "most"}) == {
        ("node:a", "invalid_value")
    }
    # A record type without approvals is told so at design time, never at run time.
    assert _problems({"approvers": {"user_ids": [PERSON]}}, FACTS) == {
        ("node:a", "approval_not_offered")
    }


# --- the task node (REQ-WF-015) -------------------------------------------------------------------


def test_req_wf_015_a_task_node_opens_its_checklist_and_continues_when_all_are_done() -> None:
    definition = flow(
        [
            node("s", "start"),
            node("do", "tasks", titles=[{"en": "Back up"}, {"en": "Patch"}], due_days=2),
            node("e", "end"),
            node("bad", "end"),
        ],
        [("s", "next", "do"), ("do", "next", "e"), ("do", "error", "bad")],
        [],
    )
    started = step(definition, State.start(definition))
    [command] = started.commands
    assert command.kind == CommandKind.OPEN_TASKS
    assert command.payload["titles"] == [{"en": "Back up"}, {"en": "Patch"}]
    assert command.payload["due_days"] == 2
    assert started.state.status == InstanceStatus.WAITING
    done = step(definition, started.state, event=CommandDone(command.id, ok=True))
    assert done.state.status == InstanceStatus.FINISHED
    canceled = step(
        definition, started.state, event=CommandDone(command.id, ok=False, error="task_canceled")
    )
    assert [s.result for s in canceled.steps if s.node == "do"] == ["error"]


def test_a_task_node_needs_titles_and_a_sensible_due_date() -> None:
    def found(config: dict[str, object]) -> set[tuple[str, str]]:
        nodes = [raw_node("s", "start"), raw_node("t", "tasks", **config), raw_node("e", "end")]
        links = [link("s", "next", "t"), link("t", "next", "e")]
        parsed = parse({"format": 1, "nodes": nodes, "links": links, "variables": []})
        assert parsed.definition is not None, parsed.problems
        return {(where, code) for where, code, _ in validate(parsed.definition, FACTS)}

    assert found({"titles": [{"en": "Back up"}]}) == set()
    assert found({}) == {("node:t", "tasks_titles_invalid")}
    assert found({"titles": [{"en": " "}]}) == {("node:t", "tasks_titles_invalid")}
    assert found({"titles": [{"en": "x"}] * 21}) == {("node:t", "tasks_titles_invalid")}
    assert found({"titles": [{"en": "x"}], "due_days": 400}) == {("node:t", "tasks_due_invalid")}
    assert found({"titles": [{"en": "x"}], "owner_user_id": "nope"}) == {
        ("node:t", "invalid_value")
    }


# --- the function node (REQ-WF-021; §6.7) -------------------------------------------------------


def test_req_wf_021_a_function_node_is_offered_only_when_licensed_and_names_what_it_uses() -> None:
    def found(config: dict[str, object], *, offered: bool = True) -> set[tuple[str, str]]:
        facts = replace(FACTS, functions=offered)
        nodes = [raw_node("s", "start"), raw_node("f", "function", **config), raw_node("e", "end")]
        links = [link("s", "next", "f"), link("f", "next", "e")]
        parsed = parse(
            {
                "format": 1,
                "nodes": nodes,
                "links": links,
                "variables": [{"name": "score", "kind": "number"}],
            }
        )
        assert parsed.definition is not None, parsed.problems
        return {(where, code) for where, code, _ in validate(parsed.definition, facts)}

    good: dict[str, object] = {"function": "score_risk", "assign": {"out": "score"}}
    assert found(good) == set()
    assert found(good, offered=False) == {("node:f", "function_not_offered")}
    assert found({"function": "Bad Name"}) == {("node:f", "function_missing")}
    assert found({**good, "timeout_seconds": 60}) == {("node:f", "function_timeout_invalid")}
    assert found({**good, "assign": {"out": "nope"}}) == {("node:f", "variable_unknown")}
    assert found({**good, "inputs": {"x": {"field": "nope"}}}) == {("node:f", "unknown_field")}
