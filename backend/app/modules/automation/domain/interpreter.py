"""The workflow interpreter: one pure step function (WP-048b S1, ADR-043 §4). No I/O.

`advance(definition, state, facts, event, now, clock)` takes an instance a step further:
- it applies what happened (a record event, a timer, the result of a command);
- it runs every token that can move until each one waits, ends or needs a command carried out;
- it returns the new state, the steps to log, the commands to carry out and the next wake time.

Commands (move the record, set fields, add a note) are carried out by the owning modules'
public services in the same transaction as the steps (ADR-043 §5-6); their results come back as
`CommandDone` events, so a node's success and error outputs are decided here too.

Parallel branches are tokens. A split gives each branch a token that remembers which split made
it (`groups`); a join counts the tokens of the same split and continues with one when its mode is
met, cancelling the others it no longer needs (REQ-WF-018).

A failed command retries when its node says so (`retries`, `retry_seconds`): the token waits and
the waker runs the node again; only then does the error output (or the stop) follow (REQ-WF-024).
A sub-flow is a command the runtime carries out itself: it starts the child instance, and the
child's end comes back to the parent as that command's result (REQ-WF-017).

Limits (Appendix A, REQ-WF-029): a token enters one node at most `max_rounds` times (100 at
most), and an instance runs at most 10,000 steps. Hitting one fails the instance, with the reason.
"""

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from app.modules.automation.domain.rules import JsonValue, matches
from app.modules.automation.domain.workflows import (
    MAX_LOOP_ROUNDS,
    MAX_STEPS,
    VAR_PREFIX,
    Definition,
    JoinMode,
    NodeType,
    TimeBasis,
    WaitEvent,
)

# Status categories in which a wait can no longer complete (ADR-043 §5 default, lane A's review).
FINAL = frozenset({"closed", "canceled"})

# Adds seconds to an instant, in calendar or business time (the sla module's Calendar, injected).
Clock = Callable[[datetime, int, TimeBasis], datetime]


class InstanceStatus(StrEnum):
    """An instance's state (REQ-WF-025)."""

    RUNNING = "running"
    WAITING = "waiting"
    FAILED = "failed"
    FINISHED = "finished"
    CANCELLED = "cancelled"


class TokenState(StrEnum):
    """Where a token is in its node."""

    READY = "ready"
    WAITING = "waiting"  # a wait or timer node
    COMMAND = "command"  # a command it asked for is being carried out
    JOINED = "joined"  # arrived at a join that is not yet met
    DONE = "done"
    CANCELLED = "cancelled"


class CommandKind(StrEnum):
    """What a command asks an owning module to do (ADR-043 §6)."""

    MOVE = "move"
    UPDATE_FIELDS = "update_fields"
    ADD_NOTE = "add_note"
    START_SUB_FLOW = "start_sub_flow"  # carried out by the runtime, not an owning module
    OPEN_APPROVAL = "open_approval"  # opened now, decided later: its result names the output
    OPEN_TASKS = "open_tasks"  # opened now, done later: all done is its result
    RUN_FUNCTION = "run_function"  # run by a worker through the runner port (§6.7)
    CALL_WEBHOOK = "call_webhook"  # sent by a worker through the guarded client (ADR-043 §8)
    NOTIFY = "notify"  # through the owning module's record, to the one notification engine


@dataclass(frozen=True)
class Group:
    """The split a token came from: the split node, its run and the branch."""

    split: str
    run: int
    branch: str


@dataclass
class Token:
    """One position in the workflow."""

    id: str
    node: str
    state: TokenState = TokenState.READY
    groups: tuple[Group, ...] = ()
    rounds: dict[str, int] = field(default_factory=dict)
    wake_at: datetime | None = None
    command: str | None = None
    attempts: int = 0  # failed tries of the node's command so far (its retries)
    retrying: bool = False  # waiting to try the node's command again


@dataclass
class Failure:
    """Why an instance stopped, and at which node (REQ-WF-024, -029)."""

    node: str
    code: str
    params: dict[str, JsonValue] = field(default_factory=dict)


@dataclass
class State:
    """Everything the interpreter knows about one instance; stored by the runtime as JSON."""

    tokens: list[Token]
    variables: dict[str, JsonValue] = field(default_factory=dict)
    steps: int = 0
    status: InstanceStatus = InstanceStatus.RUNNING
    failure: Failure | None = None
    next_id: int = 1  # the next token and command number
    split_runs: int = 0
    joins: dict[str, list[str]] = field(default_factory=dict)  # "<join>|<split>|<run>" -> tokens

    @classmethod
    def start(cls, definition: Definition) -> "State":
        """A new instance: one token at the start node."""
        start = next(n.id for n in definition.nodes if n.type == NodeType.START)
        return cls(tokens=[Token(id="t1", node=start)], next_id=2)


@dataclass(frozen=True)
class RecordChanged:
    """A committed change of the instance's record, as the workflow_events consumer saw it."""

    kind: WaitEvent


@dataclass(frozen=True)
class TimerFired:
    """The waker's wake-up: every token due by `now` moves on."""


@dataclass(frozen=True)
class CommandDone:
    """The result of a command the interpreter asked for."""

    command: str
    ok: bool
    error: str | None = None
    outputs: Mapping[str, JsonValue] = field(default_factory=dict)
    port: str | None = None  # the output a successful result leaves by ("next" when None)


Event = RecordChanged | TimerFired | CommandDone


@dataclass(frozen=True)
class Command:
    """Something a node needs done by an owning module's public service (ADR-043 §6)."""

    id: str
    token: str
    node: str
    kind: CommandKind
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class Step:
    """One line of the instance's log (REQ-WF-023): a node run, and what came of it."""

    token: str
    node: str
    node_type: NodeType
    result: str  # an output port, or waiting / command / joined / finished / cancelled / failed
    at: datetime
    detail: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass
class Advance:
    """What one call of `advance` produced."""

    state: State
    steps: list[Step]
    commands: list[Command]
    wake_at: datetime | None


@dataclass
class _Run:
    definition: Definition
    state: State
    facts: Mapping[str, JsonValue]
    now: datetime
    clock: Clock
    steps: list[Step] = field(default_factory=list)
    commands: list[Command] = field(default_factory=list)

    def seen(self) -> dict[str, JsonValue]:
        """What conditions read: the record's facts and the variables as `var.<name>`."""
        found = dict(self.facts)
        found.update({f"{VAR_PREFIX}{k}": v for k, v in self.state.variables.items()})
        return found

    def log(self, token: Token, result: str, **detail: JsonValue) -> None:
        node = self.definition.node(token.node)
        self.steps.append(Step(token.id, node.id, node.type, result, self.now, detail))

    def fail(self, token: Token, code: str, **params: JsonValue) -> None:
        self.state.status = InstanceStatus.FAILED
        self.state.failure = Failure(token.node, code, dict(params))
        self.log(token, "failed", code=code)

    def follow(self, token: Token, port: str) -> None:
        """Leave the token's node by `port`; an unlinked output stops the instance there."""
        self.log(token, port)
        target = self.definition.next_of(token.node, port)
        if target is None:
            self.fail(token, "output_not_linked", port=port)
            return
        token.node, token.state, token.wake_at, token.command = target, TokenState.READY, None, None
        token.attempts, token.retrying = 0, False

    def new_id(self, prefix: str) -> str:
        value = f"{prefix}{self.state.next_id}"
        self.state.next_id += 1
        return value


def advance(  # noqa: PLR0913 - the instance and its surroundings, explicit
    definition: Definition,
    state: State,
    facts: Mapping[str, JsonValue],
    event: Event | None,
    *,
    now: datetime,
    clock: Clock,
) -> Advance:
    """Apply `event`, then run every ready token until it waits, ends or needs a command."""
    # A copy: the caller's state stays as it was (a re-run activity starts from the stored one).
    run = _Run(definition, copy.deepcopy(state), facts, now, clock)
    if run.state.status in {InstanceStatus.RUNNING, InstanceStatus.WAITING}:
        _apply(run, event)
        _drain(run)
        _settle(run)
    alive = [t for t in run.state.tokens if t.wake_at is not None and t.state == TokenState.WAITING]
    wake = min((t.wake_at for t in alive if t.wake_at is not None), default=None)
    if run.state.status not in {InstanceStatus.RUNNING, InstanceStatus.WAITING}:
        wake = None
    return Advance(run.state, run.steps, run.commands, wake)


def _apply(run: _Run, event: Event | None) -> None:  # noqa: C901 - one branch per event kind
    if event is None:
        return
    if isinstance(event, CommandDone):
        _command_done(run, event)
        return
    for token in [t for t in run.state.tokens if t.state == TokenState.WAITING]:
        node = run.definition.node(token.node)
        if isinstance(event, TimerFired):
            if token.wake_at is None or token.wake_at > run.now:
                continue
            if token.retrying:  # the node runs again (its round counts, as a loop's would)
                token.state, token.wake_at, token.retrying = TokenState.READY, None, False
            else:
                run.follow(token, "next" if node.type == NodeType.TIMER else "timeout")
            continue
        if token.retrying:
            continue
        if node.type != NodeType.WAIT:
            continue
        if event.kind.value in node.config.get("events", []) and matches(
            node.config.get("condition"), None, run.seen()
        ):
            run.follow(token, "next")
        elif _overtaken(run, node.config):
            run.follow(token, "overtaken")  # never silently dropped (REQ-WF-012 AC2)


def _command_done(run: _Run, event: CommandDone) -> None:
    """A command's result: its success, a retry, its error output, or the stop (REQ-WF-024)."""
    token = next((t for t in run.state.tokens if t.command == event.command), None)
    if token is None or token.state != TokenState.COMMAND:
        return  # a result already applied (activities run at least once)
    config = run.definition.node(token.node).config
    if event.ok:
        run.state.variables.update(event.outputs)
        run.follow(token, event.port or "next")
    elif token.attempts < int(config.get("retries", 0)):
        token.attempts += 1
        token.state, token.command, token.retrying = TokenState.WAITING, None, True
        wait = int(config.get("retry_seconds", 60))
        token.wake_at = run.clock(run.now, wait, TimeBasis.CALENDAR)
        run.log(token, "retry", attempt=token.attempts, code=event.error or "command_failed")
    elif run.definition.next_of(token.node, "error") is not None:
        run.follow(token, "error")
    else:  # no error output: the instance stops at the node (REQ-WF-024)
        run.fail(token, event.error or "command_failed")


def _overtaken(run: _Run, config: Mapping[str, Any]) -> bool:
    if config.get("overtaken_when") is not None:
        return matches(config["overtaken_when"], None, run.seen())
    return run.facts.get("status_category") in FINAL


def _drain(run: _Run) -> None:
    """Run ready tokens one node at a time until none is ready or the instance stops."""
    while run.state.status in {InstanceStatus.RUNNING, InstanceStatus.WAITING}:
        token = next((t for t in run.state.tokens if t.state == TokenState.READY), None)
        if token is None:
            return
        run.state.steps += 1
        if run.state.steps > MAX_STEPS:
            run.fail(token, "step_limit", max=MAX_STEPS)
            return
        node = run.definition.node(token.node)
        token.rounds[node.id] = token.rounds.get(node.id, 0) + 1
        limit = min(int(node.config.get("max_rounds", MAX_LOOP_ROUNDS)), MAX_LOOP_ROUNDS)
        if token.rounds[node.id] > limit:
            run.fail(token, "loop_limit", max=limit)  # REQ-WF-029 AC1
            return
        _run_node(run, token)


def _run_node(run: _Run, token: Token) -> None:  # noqa: C901, PLR0912 - one branch per node type
    node = run.definition.node(token.node)
    config = node.config
    match node.type:
        case NodeType.START:
            run.follow(token, "next")
        case NodeType.END:
            token.state = TokenState.DONE
            run.log(token, "finished")
        case NodeType.IF:
            run.follow(token, "yes" if matches(config.get("condition"), None, run.seen()) else "no")
        case NodeType.SWITCH:
            port = next(
                (
                    str(case["port"])
                    for case in config.get("cases", [])
                    if matches(case.get("condition"), None, run.seen())
                ),
                "default",
            )
            run.follow(token, port)  # exactly one output (REQ-WF-011 AC2)
        case NodeType.SET_STATUS:
            _command(run, token, CommandKind.MOVE, {"action": config.get("action")})
        case NodeType.FIELD_UPDATE:
            _command(
                run, token, CommandKind.UPDATE_FIELDS, {"values": dict(config.get("values", {}))}
            )
        case NodeType.NOTE:
            _command(
                run,
                token,
                CommandKind.ADD_NOTE,
                {
                    "text": dict(config.get("text", {})),
                    "private": bool(config.get("private", True)),
                },
            )
        case NodeType.WAIT:
            _wait(run, token)
        case NodeType.TIMER:
            _timer(run, token)
        case NodeType.SPLIT:
            _split(run, token)
        case NodeType.JOIN:
            _join(run, token)
        case NodeType.SET_VARIABLE:
            _set_variable(run, token)
        case NodeType.SUB_FLOW:
            _command(
                run, token, CommandKind.START_SUB_FLOW, {"workflow_id": config.get("workflow_id")}
            )
        case NodeType.TASKS:
            _command(
                run,
                token,
                CommandKind.OPEN_TASKS,
                {
                    "titles": [dict(t) for t in config.get("titles", [])],
                    "owner_user_id": config.get("owner_user_id"),
                    "owner_group_id": config.get("owner_group_id"),
                    "due_days": config.get("due_days"),
                },
            )
        case NodeType.NOTIFY:
            _command(
                run,
                token,
                CommandKind.NOTIFY,
                {
                    "audience": dict(config.get("audience", {})),
                    "subject": dict(config.get("subject", {})),
                    "body": dict(config.get("body", {})),
                },
            )
        case NodeType.WEBHOOK:
            _command(
                run,
                token,
                CommandKind.CALL_WEBHOOK,
                {
                    "url": config.get("url"),
                    "method": str(config.get("method", "POST")),
                    "headers": dict(config.get("headers", {})),
                    "fields": list(config.get("fields", [])),
                    "status_variable": config.get("status_variable"),
                },
            )
        case NodeType.FUNCTION:
            _command(
                run,
                token,
                CommandKind.RUN_FUNCTION,
                {
                    "function": config.get("function"),
                    "inputs": dict(config.get("inputs", {})),
                    "assign": dict(config.get("assign", {})),
                    "timeout_seconds": int(config.get("timeout_seconds", 10)),
                },
            )
        case NodeType.APPROVAL:
            _command(
                run,
                token,
                CommandKind.OPEN_APPROVAL,
                {
                    "approvers": dict(config.get("approvers", {})),
                    "rule": str(config.get("rule", "any")),
                },
            )


def _set_variable(run: _Run, token: Token) -> None:
    config = run.definition.node(token.node).config
    source = config.get("from_field")
    value = run.facts.get(str(source)) if source is not None else config.get("value")
    run.state.variables[str(config.get("variable"))] = value
    run.follow(token, "next")


def _command(run: _Run, token: Token, kind: CommandKind, payload: Mapping[str, Any]) -> None:
    command = run.new_id("c")
    token.state, token.command = TokenState.COMMAND, command
    run.commands.append(Command(command, token.id, token.node, kind, payload))
    run.log(token, "command", kind=kind.value)


def _basis(config: Mapping[str, Any]) -> TimeBasis:
    return TimeBasis(config.get("basis", TimeBasis.CALENDAR.value))


def _wait(run: _Run, token: Token) -> None:
    config = run.definition.node(token.node).config
    # A state the wait listens for that already holds completes at once: the change it waits for
    # has happened (REQ-WF-012 AC1 when the technician was quicker than the workflow).
    if config.get("condition") is not None and matches(config["condition"], None, run.seen()):
        run.follow(token, "next")
        return
    if _overtaken(run, config):
        run.follow(token, "overtaken")
        return
    token.state = TokenState.WAITING
    limit = config.get("limit_seconds")
    token.wake_at = run.clock(run.now, int(limit), _basis(config)) if limit else None
    run.log(token, "waiting")


def _timer(run: _Run, token: Token) -> None:
    config = run.definition.node(token.node).config
    if config.get("seconds") is not None:
        due = run.clock(run.now, int(config["seconds"]), _basis(config))
    else:
        raw = run.facts.get(str(config.get("until_field")))
        if not isinstance(raw, str):  # no date on the record: nothing to wait for
            run.follow(token, "next")
            return
        due = datetime.fromisoformat(raw) + timedelta(seconds=int(config.get("offset_seconds", 0)))
    if due <= run.now:
        run.follow(token, "next")
        return
    token.state, token.wake_at = TokenState.WAITING, due
    run.log(token, "waiting", until=due.isoformat())


def _split(run: _Run, token: Token) -> None:
    config = run.definition.node(token.node).config
    run.state.split_runs += 1
    split_run = run.state.split_runs
    token.state = TokenState.DONE
    run.log(token, "split")
    for branch in config.get("branches", []):
        target = run.definition.next_of(token.node, str(branch))
        if target is None:
            run.fail(token, "output_not_linked", port=str(branch))
            return
        run.state.tokens.append(
            Token(
                id=run.new_id("t"),
                node=target,
                groups=(*token.groups, Group(token.node, split_run, str(branch))),
                rounds=dict(token.rounds),
            )
        )


def _join(run: _Run, token: Token) -> None:
    node = run.definition.node(token.node)
    if not token.groups:
        run.fail(token, "join_without_split")
        return
    group = token.groups[-1]
    key = f"{node.id}|{group.split}|{group.run}"
    arrived = run.state.joins.setdefault(key, [])
    arrived.append(token.id)
    token.state = TokenState.JOINED
    branches = len(run.definition.node(group.split).config.get("branches", []))
    mode = JoinMode(node.config.get("mode", JoinMode.ALL.value))
    needed = {JoinMode.ALL: branches, JoinMode.FIRST: 1}.get(mode, int(node.config.get("count", 1)))
    run.log(token, "joined", arrived=len(arrived), needed=needed)
    if len(arrived) < needed:
        return
    for other in run.state.tokens:
        same = bool(other.groups) and (other.groups[-1].split, other.groups[-1].run) == (
            group.split,
            group.run,
        )
        if not same or other.state in {TokenState.DONE, TokenState.CANCELLED}:
            continue
        if other.id in arrived:
            other.state = TokenState.DONE
        else:  # still running: "first" and "count" joins cancel the rest (REQ-WF-018 AC2)
            other.state = TokenState.CANCELLED
            run.log(other, "cancelled", by_join=node.id)
    run.state.joins.pop(key, None)
    joined = Token(
        id=run.new_id("t"), node=node.id, groups=token.groups[:-1], rounds=dict(token.rounds)
    )
    run.state.tokens.append(joined)
    run.follow(joined, "next")


def _settle(run: _Run) -> None:
    """The instance's state from its tokens; finished tokens are dropped from the state."""
    if run.state.status == InstanceStatus.FAILED:
        return
    live = [t for t in run.state.tokens if t.state not in {TokenState.DONE, TokenState.CANCELLED}]
    run.state.tokens = live
    if not live:
        run.state.status = InstanceStatus.FINISHED
    elif any(t.state == TokenState.READY for t in live):
        run.state.status = InstanceStatus.RUNNING
    else:
        run.state.status = InstanceStatus.WAITING
