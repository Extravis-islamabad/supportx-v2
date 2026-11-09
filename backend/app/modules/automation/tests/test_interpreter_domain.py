"""The workflow interpreter, node by node (WP-048b S1, ADR-043 §4; REQ-WF-009 AC2). No I/O."""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.automation.domain.interpreter import (
    Advance,
    CommandDone,
    CommandKind,
    InstanceStatus,
    RecordChanged,
    State,
    TimerFired,
    advance,
)
from app.modules.automation.domain.workflows import (
    Definition,
    TimeBasis,
    WaitEvent,
    parse,
)

NOW = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


def clock(start: datetime, seconds: int, basis: TimeBasis) -> datetime:
    """Calendar time; business time skips a day, as a stand-in for the sla Calendar."""
    extra = timedelta(days=1) if basis == TimeBasis.BUSINESS else timedelta()
    return start + timedelta(seconds=seconds) + extra


def node(node_id: str, kind: str, **config: Any) -> dict[str, Any]:  # noqa: ANN401 - JSON
    return {"id": node_id, "type": kind, "config": config, "position": {"x": 0, "y": 0}}


def flow(nodes: list[dict[str, Any]], links: list[tuple[str, str, str]]) -> Definition:
    parsed = parse(
        {
            "format": 1,
            "nodes": nodes,
            "links": [{"from": a, "port": p, "to": b} for a, p, b in links],
        }
    )
    assert parsed.definition is not None, parsed.problems
    return parsed.definition


def step(
    definition: Definition,
    state: State,
    facts: dict[str, Any] | None = None,
    event: Any = None,  # noqa: ANN401 - one of the events
    now: datetime = NOW,
) -> Advance:
    return advance(definition, state, facts or {}, event, now=now, clock=clock)


P1 = {"field": "priority", "op": "eq", "value": "p1"}


def test_req_wf_011_ac1_if_takes_yes_for_p1_and_no_otherwise() -> None:
    definition = flow(
        [node("s", "start"), node("if", "if", condition=P1), node("e", "end")],
        [("s", "next", "if"), ("if", "yes", "e"), ("if", "no", "e")],
    )
    p1 = step(definition, State.start(definition), {"priority": "p1"})
    assert [s.result for s in p1.steps if s.node == "if"] == ["yes"]
    assert p1.state.status == InstanceStatus.FINISHED
    p3 = step(definition, State.start(definition), {"priority": "p3"})
    assert [s.result for s in p3.steps if s.node == "if"] == ["no"]


def test_req_wf_011_ac2_a_switch_always_takes_exactly_one_output() -> None:
    cases = [
        {"port": f"c{i}", "condition": {"field": "category", "op": "eq", "value": f"k{i}"}}
        for i in range(3)
    ]
    definition = flow(
        [node("s", "start"), node("sw", "switch", cases=cases), node("e", "end")],
        [
            ("s", "next", "sw"),
            ("sw", "c0", "e"),
            ("sw", "c1", "e"),
            ("sw", "c2", "e"),
            ("sw", "default", "e"),
        ],
    )
    for category, port in [("k1", "c1"), ("k2", "c2"), ("other", "default")]:
        done = step(definition, State.start(definition), {"category": category})
        assert [s.result for s in done.steps if s.node == "sw"] == [port]


def test_actions_are_commands_and_their_results_choose_the_output() -> None:
    definition = flow(
        [
            node("s", "start"),
            node("mv", "set_status", action="start_progress"),
            node("n", "note", text={"en": "Fallback"}),
            node("e", "end"),
        ],
        [("s", "next", "mv"), ("mv", "next", "e"), ("mv", "error", "n"), ("n", "next", "e")],
    )
    first = step(definition, State.start(definition))
    assert first.state.status == InstanceStatus.WAITING
    [move] = first.commands
    assert (move.kind, move.payload) == (CommandKind.MOVE, {"action": "start_progress"})
    refused = step(definition, first.state, event=CommandDone(move.id, ok=False, error="refused"))
    [note] = refused.commands
    assert note.kind == CommandKind.ADD_NOTE  # the error output, never forced (ADR-043 §6)
    again = step(definition, refused.state, event=CommandDone(move.id, ok=True))
    assert again.commands == []  # a result applied twice changes nothing (at-least-once runs)
    done = step(definition, refused.state, event=CommandDone(note.id, ok=True))
    assert done.state.status == InstanceStatus.FINISHED


def test_req_wf_024_a_failed_command_with_no_error_output_stops_at_the_node() -> None:
    definition = flow(
        [node("s", "start"), node("n", "note", text={"en": "x"}), node("e", "end")],
        [("s", "next", "n"), ("n", "next", "e")],
    )
    first = step(definition, State.start(definition))
    stopped = step(
        definition, first.state, event=CommandDone(first.commands[0].id, ok=False, error="boom")
    )
    assert stopped.state.status == InstanceStatus.FAILED
    assert stopped.state.failure is not None
    assert (stopped.state.failure.node, stopped.state.failure.code) == ("n", "boom")


IN_PROGRESS = {"field": "status", "op": "eq", "value": "in_progress"}


def waiting_flow(**config: Any) -> Definition:  # noqa: ANN401 - JSON
    return flow(
        [
            node("s", "start"),
            node("w", "wait", events=["status_changed"], condition=IN_PROGRESS, **config),
            node("ok", "end"),
            node("late", "end"),
            node("over", "end"),
        ],
        [("s", "next", "w"), ("w", "next", "ok"), ("w", "overtaken", "over")]
        + ([("w", "timeout", "late")] if config.get("limit_seconds") else []),
    )


def test_req_wf_012_ac1_a_wait_completes_when_a_person_makes_the_change() -> None:
    definition = waiting_flow()
    waiting = step(definition, State.start(definition), {"status": "open"})
    assert waiting.state.status == InstanceStatus.WAITING
    moved = step(
        definition,
        waiting.state,
        {"status": "in_progress"},
        RecordChanged(WaitEvent.STATUS_CHANGED),
    )
    assert [s.result for s in moved.steps if s.node == "w"] == ["next"]
    assert moved.state.status == InstanceStatus.FINISHED


def test_req_wf_012_ac2_a_wait_that_can_no_longer_complete_is_overtaken() -> None:
    definition = waiting_flow()
    waiting = step(definition, State.start(definition), {"status": "open"})
    closed = step(
        definition,
        waiting.state,
        {"status": "closed", "status_category": "closed"},
        RecordChanged(WaitEvent.STATUS_CHANGED),
    )
    assert [s.result for s in closed.steps if s.node == "w"] == ["overtaken"]  # never dropped


def test_req_wf_012_ac3_a_wait_with_a_limit_takes_the_timeout_output() -> None:
    definition = waiting_flow(limit_seconds=2 * 24 * 3600)
    waiting = step(definition, State.start(definition), {"status": "open"})
    assert waiting.wake_at == NOW + timedelta(days=2)
    early = step(
        definition, waiting.state, {"status": "open"}, TimerFired(), NOW + timedelta(days=1)
    )
    assert early.state.status == InstanceStatus.WAITING
    late = step(
        definition, waiting.state, {"status": "open"}, TimerFired(), NOW + timedelta(days=2)
    )
    assert [s.result for s in late.steps if s.node == "w"] == ["timeout"]


def test_req_wf_013_timers_by_duration_business_time_and_a_date_field() -> None:
    definition = flow(
        [node("s", "start"), node("t", "timer", seconds=3600, basis="business"), node("e", "end")],
        [("s", "next", "t"), ("t", "next", "e")],
    )
    waiting = step(definition, State.start(definition))
    assert waiting.wake_at == NOW + timedelta(days=1, hours=1)  # business time from the clock
    # AC1: "until scheduled start minus one day".
    before = flow(
        [
            node("s", "start"),
            node("t", "timer", until_field="scheduled_start", offset_seconds=-24 * 3600),
            node("e", "end"),
        ],
        [("s", "next", "t"), ("t", "next", "e")],
    )
    start = (NOW + timedelta(days=3)).isoformat()
    armed = step(before, State.start(before), {"scheduled_start": start})
    assert armed.wake_at == NOW + timedelta(days=2)
    fired = step(before, armed.state, {"scheduled_start": start}, TimerFired(), armed.wake_at)
    assert fired.state.status == InstanceStatus.FINISHED


def split_join(mode: str, **config: Any) -> Definition:  # noqa: ANN401 - JSON
    return flow(
        [
            node("s", "start"),
            node("sp", "split", branches=["it", "hr"]),
            node("it", "note", text={"en": "IT tasks"}),
            node("hr", "note", text={"en": "HR tasks"}),
            node("j", "join", mode=mode, **config),
            node("e", "end"),
        ],
        [
            ("s", "next", "sp"),
            ("sp", "it", "it"),
            ("sp", "hr", "hr"),
            ("it", "next", "j"),
            ("hr", "next", "j"),
            ("j", "next", "e"),
        ],
    )


def test_req_wf_018_ac1_wait_for_all_continues_only_after_both_branches() -> None:
    definition = split_join("all")
    first = step(definition, State.start(definition))
    it, hr = first.commands
    one = step(definition, first.state, event=CommandDone(it.id, ok=True))
    assert one.state.status == InstanceStatus.WAITING
    both = step(definition, one.state, event=CommandDone(hr.id, ok=True))
    assert both.state.status == InstanceStatus.FINISHED


def test_req_wf_018_ac2_wait_for_first_cancels_the_others_with_history() -> None:
    definition = split_join("first")
    first = step(definition, State.start(definition))
    it, _hr = first.commands
    done = step(definition, first.state, event=CommandDone(it.id, ok=True))
    assert done.state.status == InstanceStatus.FINISHED
    assert [(s.node, s.result) for s in done.steps if s.result == "cancelled"] == [
        ("hr", "cancelled")
    ]


def test_req_wf_029_ac1_a_loop_stops_at_its_round_limit() -> None:
    again = {"field": "approved", "op": "eq", "value": False}
    definition = flow(
        [node("s", "start"), node("ask", "if", condition=again, max_rounds=100), node("e", "end")],
        [("s", "next", "ask"), ("ask", "yes", "ask"), ("ask", "no", "e")],
    )
    stopped = step(definition, State.start(definition), {"approved": False})
    assert stopped.state.status == InstanceStatus.FAILED
    assert stopped.state.failure is not None
    assert (stopped.state.failure.code, stopped.state.failure.params) == (
        "loop_limit",
        {"max": 100},
    )


def test_the_caller_s_state_is_never_changed() -> None:
    definition = waiting_flow()
    state = State.start(definition)
    step(definition, state, {"status": "open"})
    assert state.tokens[0].node == "s"
    assert state.status == InstanceStatus.RUNNING
