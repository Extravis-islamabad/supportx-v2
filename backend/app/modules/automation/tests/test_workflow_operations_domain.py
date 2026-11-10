"""Stop, restart and retry an instance (WP-048b S3a; REQ-WF-025 AC2, REQ-WF-026). No I/O."""

import pytest

from app.modules.automation.domain.interpreter import (
    CommandDone,
    CommandKind,
    InstanceStatus,
    State,
    TokenState,
)
from app.modules.automation.domain.operations import OperationRefused, restart, retry, stop
from app.modules.automation.tests.test_interpreter_domain import NOW, flow, node, step

P1 = {"field": "priority", "op": "eq", "value": "p1"}

# Wait for P1, then set a field; the field step has no error output, so a failed command stops
# the instance there (REQ-WF-024).
FLOW = flow(
    [
        node("s", "start"),
        node("wait", "wait", event="record_changed", condition=P1),
        node("set", "field_update", values={"impact": "high"}),
        node("e", "end"),
    ],
    [("s", "next", "wait"), ("wait", "next", "set"), ("set", "next", "e")],
)


def _waiting() -> State:
    return step(FLOW, State.start(FLOW)).state


# Straight to the field step, which has no error output.
DIRECT = flow(
    [node("s", "start"), node("set", "field_update", values={"impact": "high"}), node("e", "end")],
    [("s", "next", "set"), ("set", "next", "e")],
)


def _failed() -> State:
    at_set = step(DIRECT, State.start(DIRECT))
    [command] = [c for c in at_set.commands if c.kind is CommandKind.UPDATE_FIELDS]
    done = step(DIRECT, at_set.state, event=CommandDone(command.id, ok=False))
    assert done.state.status is InstanceStatus.FAILED
    return done.state


def test_stop_cancels_every_token_keeps_the_variables_and_logs_it() -> None:
    state = _waiting()
    state.variables["kept"] = 1
    stopped = stop(FLOW, state, at=NOW)
    assert stopped.state.status is InstanceStatus.CANCELLED
    assert {t.state for t in stopped.state.tokens} == {TokenState.CANCELLED}
    assert stopped.state.variables == {"kept": 1}
    assert [(s.node, s.result) for s in stopped.steps] == [("wait", "stopped")]
    assert state.status is InstanceStatus.WAITING  # the caller's state is untouched
    with pytest.raises(OperationRefused) as refused:
        stop(FLOW, stopped.state, at=NOW)
    assert refused.value.code == "instance_not_running"


def test_restart_runs_again_from_the_start_or_from_a_chosen_node() -> None:
    stopped = stop(FLOW, _waiting(), at=NOW).state
    stopped.variables["kept"] = 1
    again = restart(FLOW, stopped, at=NOW)
    assert (again.state.status, [t.node for t in again.state.tokens]) == (
        InstanceStatus.RUNNING,
        ["s"],
    )
    assert again.state.variables == {}  # from the start: a clean run
    at_set = restart(FLOW, stopped, at=NOW, node="set")
    assert [t.node for t in at_set.state.tokens] == ["set"]
    assert at_set.state.variables == {"kept": 1}  # from a node: what came before is kept
    assert [(s.node, s.result, s.detail) for s in at_set.steps] == [
        ("set", "restarted", {"node": "set"})
    ]
    # It runs on from there: the field step asks for its command at once.
    ran = step(FLOW, at_set.state)
    assert [c.kind for c in ran.commands] == [CommandKind.UPDATE_FIELDS]


@pytest.mark.parametrize(
    ("chosen", "code"),
    [("nowhere", "node_not_found"), ("e", "restart_at_end")],
)
def test_restart_refuses_a_running_instance_and_a_node_it_cannot_run(
    chosen: str, code: str
) -> None:
    with pytest.raises(OperationRefused) as running:
        restart(FLOW, _waiting(), at=NOW)
    assert running.value.code == "instance_running"
    stopped = stop(FLOW, _waiting(), at=NOW).state
    with pytest.raises(OperationRefused) as refused:
        restart(FLOW, stopped, at=NOW, node=chosen)
    assert refused.value.code == code


def test_retry_runs_the_failed_node_again() -> None:
    failed = _failed()
    retried = retry(DIRECT, failed, at=NOW)
    assert (retried.state.status, retried.state.failure) == (InstanceStatus.RUNNING, None)
    assert [(s.node, s.result) for s in retried.steps] == [("set", "retried")]
    ran = step(DIRECT, retried.state)
    assert [c.kind for c in ran.commands] == [CommandKind.UPDATE_FIELDS]  # asked again
    with pytest.raises(OperationRefused) as refused:
        retry(FLOW, _waiting(), at=NOW)
    assert refused.value.code == "instance_not_failed"
