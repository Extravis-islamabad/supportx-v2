"""Workflow definitions and their validation (WP-048b S1, ADR-043 §1-2). No I/O."""

from typing import Any

from app.modules.automation.domain.rules import FieldKind, RuleField
from app.modules.automation.domain.workflows import (
    MAX_NODES,
    NodeType,
    TypeFacts,
    offered,
    parse,
    validate,
)

FACTS = TypeFacts(
    record_type="incident",
    fields={
        "priority": RuleField(FieldKind.CODE, frozenset({"p1", "p2", "p3"}), settable=True),
        "subject": RuleField(FieldKind.TEXT, settable=True),
        "status": RuleField(FieldKind.CODE, frozenset({"open", "in_progress"})),
    },
    settable=frozenset({"priority", "subject"}),
    actions=frozenset({"start_progress", "resolve"}),
    system_actions=frozenset({"approval_approved"}),
    date_fields=frozenset({"scheduled_start"}),
)


def node(node_id: str, kind: str, **config: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    return {"id": node_id, "type": kind, "config": config, "position": {"x": 0, "y": 0}}


def link(source: str, port: str, target: str) -> dict[str, str]:
    return {"from": source, "port": port, "to": target}


def sample() -> dict[str, Any]:
    """REQ-WF-008 AC1: start → if → note → set status → end."""
    return {
        "format": 1,
        "nodes": [
            node("start", "start"),
            node("p1", "if", condition={"field": "priority", "op": "eq", "value": "p1"}),
            node("note", "note", text={"en": "Major incident"}, private=True),
            node("move", "set_status", action="start_progress"),
            node("end", "end"),
        ],
        "links": [
            link("start", "next", "p1"),
            link("p1", "yes", "note"),
            link("p1", "no", "end"),
            link("note", "next", "move"),
            link("move", "next", "end"),
        ],
        "variables": [],
    }


def problems_of(raw: dict[str, Any]) -> list[tuple[str, str]]:
    parsed = parse(raw)
    assert parsed.definition is not None, parsed.problems
    return [
        (where, code) for where, code, _ in parsed.problems + validate(parsed.definition, FACTS)
    ]


def test_req_wf_008_a_valid_workflow_reads_back_to_the_same_definition() -> None:
    raw = sample()
    parsed = parse(raw)
    assert parsed.definition is not None
    assert validate(parsed.definition, FACTS) == []
    assert parsed.definition.to_json() == raw  # AC3: re-opens to the same diagram


def test_req_wf_019_an_unconnected_node_is_named() -> None:
    raw = sample()
    raw["nodes"].append(node("lost", "note", text={"en": "x"}))
    found = problems_of(raw)
    assert ("node:lost", "node_unreachable") in found  # AC1: the node is named
    assert ("node:lost", "output_not_linked") in found


def test_req_wf_019_ac3_any_node_may_link_to_the_end() -> None:
    raw = sample()
    raw["links"] = [x for x in raw["links"] if x["from"] != "note"] + [link("note", "next", "end")]
    raw["nodes"] = [n for n in raw["nodes"] if n["id"] != "move"]
    raw["links"] = [x for x in raw["links"] if x["from"] != "move"]
    assert problems_of(raw) == []


def test_req_wf_015_ac2_a_field_the_type_cannot_set_is_refused() -> None:
    raw = sample()
    raw["nodes"][2] = node("note", "field_update", values={"status": "open", "subject": "Hi"})
    assert ("node:note", "field_not_settable") in problems_of(raw)


def test_system_statuses_are_refused_at_design_time() -> None:
    raw = sample()
    raw["nodes"][3] = node("move", "set_status", action="approval_approved")
    assert ("node:move", "system_status_not_allowed") in problems_of(raw)


def test_a_wait_that_can_never_finish_and_a_join_without_a_split() -> None:
    raw = sample()
    raw["nodes"] += [node("w", "wait", events=[]), node("j", "join")]
    raw["links"] += [
        link("w", "next", "j"),
        link("w", "overtaken", "end"),
        link("j", "next", "end"),
    ]
    found = problems_of(raw)
    assert ("node:w", "wait_never_finishes") in found
    assert ("node:j", "join_without_split") in found


def test_req_wf_029_ac2_too_many_nodes_is_refused_with_the_limit() -> None:
    raw = sample()
    raw["nodes"] += [node(f"n{i}", "end") for i in range(MAX_NODES)]
    parsed = parse(raw)
    assert parsed.definition is None
    assert parsed.problems == [("definition", "too_many_nodes", {"max": MAX_NODES})]


def test_loop_rounds_are_capped_and_conditions_use_the_rules_grammar() -> None:
    raw = sample()
    raw["nodes"][1] = node(
        "p1", "if", condition={"field": "nope", "op": "eq", "value": 1}, max_rounds=101
    )
    found = problems_of(raw)
    assert ("node:p1", "unknown_field") in found
    assert ("node:p1", "loop_limit_invalid") in found


def test_req_wf_009_every_node_type_is_offered_for_work_items() -> None:
    assert set(offered("incident")) == set(NodeType)
