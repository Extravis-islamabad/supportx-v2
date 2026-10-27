"""Triggers, transition settings and the loop guard (WP-029 part 2). Pure: no I/O.

Requirements: REQ-RUL-009, 010, 028; REQ-WF-003, 004.

A trigger reacts to a committed event of a record. Its conditions use the business rule engine;
the event names the changed fields but not their old values, so "changed from" is offered only
for the status (the status event carries the old one). Each automated change carries its cause:
the chain depth and the triggers in the chain, so a loop stops at a clear limit and says which
triggers took part.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.modules.automation.domain.rules import (
    LANGUAGES,
    MAX_ACTIONS,
    JsonValue,
    Problem,
    RuleField,
    RuleOp,
    check_actions,
    check_conditions,
)

DEPTH_CAP = 5  # automated changes caused by one original change (D-097 item 7)
RATE_CAP = 20  # automated changes per record per minute
NOTE_MAX = 5000
CONFIRMATION_MAX = 500
_CHANGED_FROM_FIELDS = frozenset({"status"})
_SENTINEL = "\x00changed"  # stands for an unknown old value; never equals a real value


class TriggerEvent(StrEnum):
    """What a trigger reacts to (REQ-RUL-009; SLA and approval events join later)."""

    CREATED = "created"
    UPDATED = "updated"
    STATUS_CHANGED = "status_changed"
    ASSIGNED = "assigned"
    NOTE_ADDED = "note_added"
    REQUESTER_REPLIED = "requester_replied"


class TriggerActionKind(StrEnum):
    """Actions in this WP (REQ-RUL-010); notification, task, webhook ... register later."""

    SET = "set"
    NOTE = "note"


class Relative(StrEnum):
    """People relative to the record who may run a transition (REQ-WF-004)."""

    REQUESTER = "requester"
    ASSIGNEE = "assignee"
    GROUP_HEAD = "group_head"
    REQUESTER_MANAGER = "requester_manager"
    DEPARTMENT_HEAD = "department_head"


class LoopStop(StrEnum):
    """Why the guard did not run a trigger."""

    OWN_CHANGE = "own_change"  # the change this trigger's own action made (REQ-RUL-028 AC2)
    DEPTH = "depth"  # chain depth cap
    RATE = "rate"  # per-record rate cap


@dataclass(frozen=True)
class ChainLink:
    """One trigger that took part in a chain."""

    trigger_id: str
    name: str


@dataclass(frozen=True)
class Cause:
    """Where an event came from: depth 0 is a person's (or an API client's) change."""

    depth: int = 0
    chain: tuple[ChainLink, ...] = ()

    def then(self, link: ChainLink) -> "Cause":
        """The cause of the changes `link` makes when it runs on an event with this cause."""
        return Cause(self.depth + 1, (*self.chain, link))

    def names(self) -> list[str]:
        """The triggers in the chain, each once, in order."""
        seen: dict[str, str] = {}
        for link in self.chain:
            seen.setdefault(link.trigger_id, link.name)
        return list(seen.values())


def loop_stop(
    cause: Cause, trigger_id: str, *, fire_on_own_change: bool, recent_changes: int
) -> LoopStop | None:
    """Whether the guard stops `trigger_id` on an event with `cause` (None: it may run)."""
    if cause.chain and cause.chain[-1].trigger_id == trigger_id and not fire_on_own_change:
        return LoopStop.OWN_CHANGE
    if cause.depth >= DEPTH_CAP:
        return LoopStop.DEPTH
    if recent_changes >= RATE_CAP:
        return LoopStop.RATE
    return None


@dataclass(frozen=True)
class TriggerDef:
    """A trigger as the engine sees it."""

    id: str
    name: str
    events: frozenset[TriggerEvent]
    conditions: Mapping[str, Any] | None
    actions: tuple[Mapping[str, Any], ...]
    fire_on_own_change: bool = False
    site_id: str | None = None


def before_from(
    after: Mapping[str, JsonValue], changed: Sequence[str], known: Mapping[str, JsonValue]
) -> dict[str, JsonValue]:
    """A "before" snapshot for the rule engine from an event that names its changed fields.

    Changed fields get a placeholder (so "changed" and "changed to" work) unless the event
    carried the old value (`known`, e.g. the status before a move).
    """
    before = dict(after)
    for name in changed:
        before[name] = known.get(name, _SENTINEL)
    return before


def check_trigger(values: Mapping[str, Any], fields: Mapping[str, RuleField]) -> list[Problem]:
    """Problems of a trigger's events, conditions and actions (REQ-RUL-029)."""
    problems: list[Problem] = []
    events = values.get("events") or []
    if not events or not set(events) <= {e.value for e in TriggerEvent}:
        problems.append(("events", "invalid_choice", {}))
    conditions = values.get("conditions")
    if conditions is not None:
        problems += check_conditions(conditions, fields)
        problems += [
            ("conditions", "operator_not_allowed", {"field": name})
            for name in _changed_from_fields(conditions)
            if name not in _CHANGED_FROM_FIELDS
        ]
    problems += check_after_actions(values.get("actions"), fields)
    return problems


def check_after_actions(actions: Any, fields: Mapping[str, RuleField]) -> list[Problem]:  # noqa: ANN401 - untrusted JSON
    """Problems of "set a field" and "add a note" actions (triggers and transition "after")."""
    if not isinstance(actions, list) or not actions:
        return [("actions", "required", {})]
    if len(actions) > MAX_ACTIONS:
        return [("actions", "too_many_actions", {"max": MAX_ACTIONS})]
    problems: list[Problem] = []
    seen: set[str] = set()
    for index, action in enumerate(actions):
        problems += _action_problems(index, action, fields, seen)
    return problems


def _action_problems(
    index: int,
    action: Any,  # noqa: ANN401 - untrusted JSON
    fields: Mapping[str, RuleField],
    seen: set[str],
) -> list[Problem]:
    kind = action.get("kind") if isinstance(action, Mapping) else None
    if kind == TriggerActionKind.NOTE.value:
        text = str(action.get("text") or "").strip()
        if not text:
            return [(f"actions.{index}.text", "required", {})]
        if len(text) > NOTE_MAX:
            return [(f"actions.{index}.text", "value_too_long", {"max_length": NOTE_MAX})]
        return []
    if kind != TriggerActionKind.SET.value:
        return [(f"actions.{index}.kind", "invalid_choice", {})]
    name = str(action.get("field"))
    if name in seen:
        return [(f"actions.{index}.field", "field_set_twice", {"field": name})]
    seen.add(name)
    # The rule engine checks one "set" action; its paths say "actions.0", this one's index.
    return [
        (f"actions.{index}" + found.removeprefix("actions.0"), code, params)
        for found, code, params in check_actions([action], fields)
    ]


def check_confirmation(value: Any) -> list[Problem]:  # noqa: ANN401 - untrusted JSON
    """A transition's confirmation text: none, or English plus optional Arabic and Urdu."""
    if value is None:
        return []
    if not isinstance(value, Mapping) or not str(value.get("en") or "").strip():
        return [("confirmation.en", "message_required", {})]
    return [
        (f"confirmation.{language}", "value_too_long", {"max_length": CONFIRMATION_MAX})
        for language in LANGUAGES
        if len(str(value.get(language) or "")) > CONFIRMATION_MAX
    ]


def _changed_from_fields(node: Any) -> list[str]:  # noqa: ANN401 - a checked condition tree
    if not isinstance(node, Mapping):
        return []
    for join in ("and", "or"):
        if join in node and isinstance(node[join], list):
            return [name for item in node[join] for name in _changed_from_fields(item)]
    return [str(node.get("field"))] if node.get("op") == RuleOp.CHANGED_FROM.value else []


@dataclass(frozen=True)
class People:
    """Who someone is to a record, for "who may run" (REQ-WF-004)."""

    user_id: str
    role_keys: frozenset[str] = frozenset()
    group_ids: frozenset[str] = frozenset()
    relatives: frozenset[Relative] = field(default_factory=frozenset)


@dataclass(frozen=True)
class TransitionRule:
    """Who may run one transition and when it is offered (empty lists: anyone permitted)."""

    roles: frozenset[str] = frozenset()
    group_ids: frozenset[str] = frozenset()
    relatives: frozenset[Relative] = frozenset()
    conditions: Mapping[str, Any] | None = None


def may_run(rule: TransitionRule, person: People) -> bool:
    """Whether `person` is one of those the transition is limited to (any of the lists)."""
    if not (rule.roles or rule.group_ids or rule.relatives):
        return True
    return bool(
        rule.roles & person.role_keys
        or rule.group_ids & person.group_ids
        or rule.relatives & person.relatives
    )
