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

from app.modules.automation.domain.interpreter import Token, TokenState
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


__all__ = ["Wait", "WaitKind", "waits_of"]
