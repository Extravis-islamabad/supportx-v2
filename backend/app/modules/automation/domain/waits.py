"""What a waiting workflow run waits for, for the record's banner (WP-047a S5; REQ-SR-053 AC1).

Pure: from the run's live tokens and its version's nodes. A wait node with a condition waits
for the fields it names; a timer waits for a date (a field's, or a moment); a task checklist
waits for its tasks; an approval for its decision; any other wait for the events it listens to.
Codes and field keys only: the screen labels them (P9).
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.modules.automation.domain.interpreter import CommandKind, Step, Token, TokenState
from app.modules.automation.domain.workflows import Definition, Node, NodeType


class WaitKind(StrEnum):
    """What a run waits for."""

    FIELD = "field"  # a field to be filled or changed (a wait node's condition)
    DATE = "date"  # a time: a date field's, or a set moment (a timer)
    TASK = "task"  # a checklist of tasks on the record to be done
    APPROVAL = "approval"  # an approval on the record to be decided
    EVENT = "event"  # something to happen on the record (a note, a reply ...)


@dataclass(frozen=True)
class Wait:
    """One place the run waits: its node, the kind, and what it names."""

    node: str
    kind: WaitKind
    fields: tuple[str, ...] = ()
    events: tuple[str, ...] = ()
    until: datetime | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


def _condition_fields(condition: Any) -> list[str]:  # noqa: ANN401 - the shared condition JSON
    """The fields a condition's leaves read, in order, once each."""
    if not isinstance(condition, Mapping):
        return []
    found: list[str] = []
    for key in ("and", "or"):
        for part in condition.get(key) or []:
            found += _condition_fields(part)
    if isinstance(condition.get("field"), str):
        found.append(condition["field"])
    return list(dict.fromkeys(found))


def _wait_node(token: Token, config: Mapping[str, Any]) -> Wait:
    fields = _condition_fields(config.get("condition"))
    if fields:
        return Wait(token.node, WaitKind.FIELD, fields=tuple(fields), until=token.wake_at)
    events = tuple(str(e) for e in config.get("events") or [])
    return Wait(token.node, WaitKind.EVENT, events=events, until=token.wake_at)


def _timer_node(token: Token, config: Mapping[str, Any]) -> Wait:
    until = config.get("until_field")
    fields = (str(until),) if isinstance(until, str) else ()
    return Wait(token.node, WaitKind.DATE, fields=fields, until=token.wake_at)


def _tasks_node(token: Token, config: Mapping[str, Any]) -> Wait:
    del config
    return Wait(token.node, WaitKind.TASK, until=token.wake_at)


def _approval_node(token: Token, config: Mapping[str, Any]) -> Wait:
    del config
    return Wait(token.node, WaitKind.APPROVAL, until=token.wake_at)


_READERS: dict[NodeType, Callable[[Token, Mapping[str, Any]], Wait]] = {
    NodeType.WAIT: _wait_node,
    NodeType.TIMER: _timer_node,
    NodeType.TASKS: _tasks_node,
    NodeType.APPROVAL: _approval_node,
}


def _wait_of(token: Token, nodes: Mapping[str, Node]) -> Wait | None:
    node = nodes.get(token.node)
    reader = _READERS.get(node.type) if node is not None else None
    return reader(token, node.config) if reader is not None and node is not None else None


def waits_of(tokens: Iterable[Token], definition: Definition) -> list[Wait]:
    """Where the run waits now, one entry per waiting node (none while it simply runs)."""
    nodes = {n.id: n for n in definition.nodes}
    found: dict[str, Wait] = {}
    for token in tokens:
        if token.state not in {TokenState.WAITING, TokenState.COMMAND}:
            continue
        wait = _wait_of(token, nodes)
        if wait is not None and wait.node not in found:
            found[wait.node] = wait
    return [found[n] for n in sorted(found)]


def kind_of(node: Node) -> WaitKind | None:
    """What a node waits for, from its type and config (None: it never waits)."""
    if node.type is NodeType.WAIT:
        return WaitKind.FIELD if _condition_fields(node.config.get("condition")) else WaitKind.EVENT
    return {
        NodeType.TIMER: WaitKind.DATE,
        NodeType.TASKS: WaitKind.TASK,
        NodeType.APPROVAL: WaitKind.APPROVAL,
    }.get(node.type)


# The commands a run waits on people for (an approval to be decided, tasks to be done).
_PEOPLE_COMMANDS = frozenset({CommandKind.OPEN_APPROVAL.value, CommandKind.OPEN_TASKS.value})


def waits_started(steps: Iterable[Step]) -> list[str]:
    """The nodes whose wait began in these steps (one save's log), each once, in order.

    From the transition only (lane B's condition 1): a node logs `waiting`, or opens an
    approval or tasks, when a token arrives, never while it stays. So a re-save, a retry or an
    unrelated edit while waiting starts nothing, and a loop back to the same node starts it again.
    """
    started: dict[str, None] = {}
    for step in steps:
        if step.result == "waiting" or (
            step.result == "command" and step.detail.get("kind") in _PEOPLE_COMMANDS
        ):
            started.setdefault(step.node, None)
    return list(started)


__all__ = ["Wait", "WaitKind", "kind_of", "waits_of", "waits_started"]
