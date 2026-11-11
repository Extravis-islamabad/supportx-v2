"""What an admin does to an instance: stop, restart, retry, migrate (REQ-WF-021, -025, -026).

Pure functions on the interpreter's `State`: each returns a new state and the log lines to
store. The runtime saves them and runs the instance on (`advance` with no event). The log is
never cleared (REQ-WF-026: ServiceDesk Plus's revoke erases it; ours keeps every line).
"""

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from app.modules.automation.domain.interpreter import (
    Failure,
    InstanceStatus,
    State,
    Step,
    Token,
    TokenState,
)
from app.modules.automation.domain.rules import JsonValue
from app.modules.automation.domain.workflows import Definition, NodeType

LIVE = frozenset({InstanceStatus.RUNNING, InstanceStatus.WAITING})


class OperationRefused(ValueError):
    """The instance is not in a state the operation applies to; `code` says why."""

    def __init__(self, *, code: str, **params: JsonValue) -> None:
        super().__init__(code)
        self.code = code
        self.params = params


@dataclass(frozen=True)
class Operated:
    """The new state and the log lines that record what was done."""

    state: State
    steps: list[Step]


def _line(
    definition: Definition, token: Token, result: str, at: datetime, **detail: JsonValue
) -> Step:
    node = definition.node(token.node)
    return Step(token.id, node.id, node.type, result, at, detail)


def stop(definition: Definition, state: State, *, at: datetime) -> Operated:
    """Stop a running or waiting instance: every token cancelled, the variables kept."""
    if state.status not in LIVE:
        raise OperationRefused(code="instance_not_running", status=state.status.value)
    stopped = copy.deepcopy(state)
    steps = [_line(definition, t, "stopped", at) for t in stopped.tokens]
    for token in stopped.tokens:
        token.state, token.wake_at, token.command = TokenState.CANCELLED, None, None
    stopped.status = InstanceStatus.CANCELLED
    return Operated(stopped, steps)


def restart(
    definition: Definition, state: State, *, at: datetime, node: str | None = None
) -> Operated:
    """Run again from the start, or from `node`, on the instance's own version.

    Allowed on a stopped, failed or finished instance (a running one is stopped first). From a
    chosen node the variables are kept, so the nodes after it read what came before; from the
    start, they are cleared. The step and loop counts start again.
    """
    if state.status in LIVE:
        raise OperationRefused(code="instance_running")
    target = node or next(n.id for n in definition.nodes if n.type is NodeType.START)
    found = next((n for n in definition.nodes if n.id == target), None)
    if found is None:
        raise OperationRefused(code="node_not_found", node=target)
    if found.type is NodeType.END:
        raise OperationRefused(code="restart_at_end", node=target)
    token = Token(id=f"t{state.next_id}", node=target)
    restarted = State(
        tokens=[token],
        variables=dict(state.variables) if node is not None else {},
        next_id=state.next_id + 1,
    )
    return Operated(restarted, [_line(definition, token, "restarted", at, node=target)])


def retry(definition: Definition, state: State, *, at: datetime) -> Operated:
    """Run a failed instance's failed node again (REQ-WF-025 AC2)."""
    if state.status is not InstanceStatus.FAILED or state.failure is None:
        raise OperationRefused(code="instance_not_failed", status=state.status.value)
    failed: Failure = state.failure
    retried = copy.deepcopy(state)
    token = next((t for t in retried.tokens if t.node == failed.node), None)
    if token is None:  # the failure left no token there (a definition's own fault)
        raise OperationRefused(code="nothing_to_retry", node=failed.node)
    token.state, token.command, token.wake_at = TokenState.READY, None, None
    token.attempts, token.retrying = 0, False
    retried.status, retried.failure = InstanceStatus.RUNNING, None
    return Operated(retried, [_line(definition, token, "retried", at, code=failed.code)])


SKIP_PORT = "next"  # the only output a skip may take (the coordinator: never a guessed branch)


def skip(definition: Definition, state: State, *, at: datetime) -> Operated:
    """Move a failed instance past its failed node, on that node's "next" output (REQ-WF-024 AC2).

    Only "next": a node whose outputs decide the path (yes/no, approved/rejected, a switch's
    cases) has no right answer to guess, so a skip there is refused; so is one whose "next" is not
    linked. The variables stay as they were; the step is logged as skipped.
    """
    if state.status is not InstanceStatus.FAILED or state.failure is None:
        raise OperationRefused(code="instance_not_failed", status=state.status.value)
    failed: Failure = state.failure
    target = definition.next_of(failed.node, SKIP_PORT)
    if target is None:
        raise OperationRefused(code="skip_without_next", node=failed.node)
    skipped = copy.deepcopy(state)
    token = next((t for t in skipped.tokens if t.node == failed.node), None)
    if token is None:  # the failure left no token there (a definition's own fault)
        raise OperationRefused(code="nothing_to_retry", node=failed.node)
    line = _line(definition, token, "skipped", at, code=failed.code, to=target)
    token.node, token.state, token.command, token.wake_at = target, TokenState.READY, None, None
    token.attempts, token.retrying = 0, False
    skipped.status, skipped.failure = InstanceStatus.RUNNING, None
    return Operated(skipped, [line])


def migrate(
    old: Definition,
    new: Definition,
    state: State,
    mapping: Mapping[str, str],
    *,
    at: datetime,
) -> Operated:
    """Move a running or waiting instance onto a new version (REQ-WF-021).

    Each token goes to `mapping[node]`, or to the node of the same ID when the new version has
    one. A token keeps its place when the node is of the same type; one mapped to another type
    of node runs that node afresh. Refused, so the instance stays on its version and is listed:
    a node with no place in the new version, a command in flight that would land on another
    type of node, and a run inside parallel branches (its join counts belong to the old graph).
    """
    if state.status not in LIVE:
        raise OperationRefused(code="instance_not_running", status=state.status.value)
    if state.joins or any(t.groups for t in state.tokens):
        raise OperationRefused(code="parallel_in_progress")
    new_ids = {n.id: n for n in new.nodes}
    moved = copy.deepcopy(state)
    steps: list[Step] = []
    for token in moved.tokens:
        before = old.node(token.node)
        target = mapping.get(token.node) or (token.node if token.node in new_ids else None)
        if target is None or target not in new_ids:
            raise OperationRefused(code="node_not_mapped", node=token.node)
        after = new_ids[target]
        if after.type is NodeType.END:
            raise OperationRefused(code="restart_at_end", node=target)
        if before.type is not after.type:
            if token.state is TokenState.COMMAND:  # its result would land on another node
                raise OperationRefused(code="command_in_flight", node=token.node)
            token.state, token.wake_at, token.command = TokenState.READY, None, None
            token.attempts, token.retrying = 0, False
        token.node = target
        steps.append(_line(new, token, "migrated", at, node=before.id))
    return Operated(moved, steps)
