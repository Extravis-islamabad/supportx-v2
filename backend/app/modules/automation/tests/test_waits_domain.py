"""What a waiting run waits for (WP-047a S5; REQ-SR-053 AC1): pure, no I/O."""

from datetime import UTC, datetime

from app.modules.automation.domain.interpreter import Step, Token, TokenState
from app.modules.automation.domain.waits import WaitKind, waits_of, waits_started
from app.modules.automation.domain.workflows import Definition, Node, NodeType

AT = datetime(2026, 11, 25, 9, 0, tzinfo=UTC)


def _node(node_id: str, kind: NodeType, **config: object) -> Node:
    return Node(node_id, kind, config, (0.0, 0.0))


FLOW = Definition(
    nodes=(
        _node(
            "w_field",
            NodeType.WAIT,
            events=["field_changed"],
            condition={
                "and": [
                    {"field": "serial", "op": "is_not_null"},
                    {"field": "model", "op": "eq", "value": "pro"},
                ]
            },
        ),
        _node("w_note", NodeType.WAIT, events=["note_added"], limit_seconds=3600),
        _node("t_date", NodeType.TIMER, until_field="needed_by"),
        _node("tasks", NodeType.TASKS),
        _node("ask", NodeType.APPROVAL),
        _node("set", NodeType.FIELD_UPDATE),
    ),
    links=(),
)


def _token(node: str, state: TokenState, wake: datetime | None = None) -> Token:
    return Token(id=node, node=node, state=state, wake_at=wake)


def test_each_wait_names_what_it_waits_for() -> None:
    waits = waits_of(
        [
            _token("w_field", TokenState.WAITING),
            _token("w_note", TokenState.WAITING, AT),
            _token("t_date", TokenState.WAITING, AT),
            _token("tasks", TokenState.COMMAND),
            _token("ask", TokenState.COMMAND),
        ],
        FLOW,
    )
    by_node = {w.node: w for w in waits}
    assert by_node["w_field"].kind is WaitKind.FIELD
    assert by_node["w_field"].fields == ("serial", "model")
    assert (by_node["w_note"].kind, by_node["w_note"].events) == (WaitKind.EVENT, ("note_added",))
    assert by_node["w_note"].until == AT
    assert (by_node["t_date"].kind, by_node["t_date"].fields) == (WaitKind.DATE, ("needed_by",))
    assert by_node["tasks"].kind is WaitKind.TASK
    assert by_node["ask"].kind is WaitKind.APPROVAL


def test_running_done_and_unknown_nodes_wait_for_nothing() -> None:
    waits = waits_of(
        [
            _token("set", TokenState.COMMAND),  # a field update: not a wait
            _token("w_field", TokenState.DONE),
            _token("gone", TokenState.WAITING),  # not in this version
        ],
        FLOW,
    )
    assert waits == []


def _step(node: str, result: str, **detail: object) -> Step:
    return Step(node, node, NodeType.WAIT, result, AT, dict(detail))


def test_waits_started_counts_the_transition_only() -> None:
    """Lane B's condition 1: entering starts a wait; staying, leaving or retrying never does."""
    entered = [_step("w_field", "waiting"), _step("ask", "command", kind="open_approval")]
    assert waits_started(entered) == ["w_field", "ask"]
    assert waits_started([]) == []  # a re-save, or an unrelated edit while waiting
    assert waits_started([_step("w_field", "next")]) == []  # leaving by its output
    retried = [_step("call", "command", kind="webhook")]  # a retry of an outside call
    assert waits_started(retried) == []
    tasks = [_step("tasks", "command", kind="open_tasks")]
    assert waits_started(tasks) == ["tasks"]


def test_a_loop_back_to_the_same_wait_starts_it_again_once_per_save() -> None:
    looped = [_step("w_field", "next"), _step("w_field", "waiting")]
    assert waits_started(looped) == ["w_field"]
    twice = [_step("w_field", "waiting"), _step("w_field", "waiting")]  # two tokens, one node
    assert waits_started(twice) == ["w_field"]
