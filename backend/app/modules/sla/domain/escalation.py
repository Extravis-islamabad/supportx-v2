"""Escalation levels and when they run (REQ-SLA-019, 022..025; wp-025-plan.md §3.4, §3.5).

Pure: no I/O. A level sits on the target's business-time line, measured from the due moment or
from the warning point: "1 hour before due" runs when the clock has used `target - 1 h` of
business time, "2 hours after" at `target + 2 h`. So a pause holds every waiting level and a
resume moves it by exactly the paused business time (REQ-SLA-025 AC2), and a change of target
moves the levels with the due moment.

A due date set by hand has no business-time share: its levels are measured from the date set,
with business time after it and wall time before it (`level_moment`).
"""

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.modules.sla.domain.calendar import Calendar
from app.modules.sla.domain.policy import TargetClock, TargetKind, TargetState

MAX_LEVELS = 8  # per target; REQ-SLA-022 asks for at least four
MAX_OFFSET_SECONDS = 30 * 24 * 3600  # a level at most 30 business days from its anchor
MAX_RECIPIENTS = 20
MAX_ACTIONS = 10
NOTE_MAX = 2000


class Anchor(enum.StrEnum):
    """What a level's offset is measured from."""

    DUE = "due"
    WARNING = "warning"  # the warning point counts as a level when the admin wants (AC 022)


class RecipientKind(enum.StrEnum):
    """Who a level tells (REQ-SLA-023). Site and change managers wait for their fields (D12)."""

    ASSIGNEE = "assignee"
    GROUP_HEAD = "group_head"
    ASSIGNEE_MANAGER = "assignee_manager"
    REQUESTER_MANAGER = "requester_manager"
    DEPARTMENT_HEAD = "department_head"
    USER = "user"  # a named person
    GROUP = "group"  # everyone in a support group


RELATIVE = frozenset(
    {
        RecipientKind.ASSIGNEE,
        RecipientKind.GROUP_HEAD,
        RecipientKind.ASSIGNEE_MANAGER,
        RecipientKind.REQUESTER_MANAGER,
        RecipientKind.DEPARTMENT_HEAD,
    }
)


class ActionKind(enum.StrEnum):
    """What a level does besides telling people (REQ-SLA-024)."""

    REASSIGN_GROUP = "reassign_group"
    REASSIGN_PERSON = "reassign_person"
    RAISE_PRIORITY = "raise_priority"  # one step up, never above the highest
    ADD_NOTE = "add_note"  # a private note on the record


class RunState(enum.StrEnum):
    """One level's run for one target clock (unique per target and level: never twice)."""

    WAITING = "waiting"
    RAN = "ran"
    CANCELLED = "cancelled"  # met, resolved, closed or canceled first (REQ-SLA-025)


@dataclass(frozen=True)
class Recipient:
    """One recipient: a relative of the record, a named person or a support group."""

    kind: RecipientKind
    id: str | None = None  # the person or group, for USER and GROUP

    def as_json(self) -> dict[str, Any]:
        """As stored in the level and its snapshot."""
        return {"kind": self.kind.value, "id": self.id}


@dataclass(frozen=True)
class Action:
    """One action: a target group or person, or a note's text."""

    kind: ActionKind
    target_id: str | None = None  # the group or person for a reassign
    text: str | None = None  # the note

    def as_json(self) -> dict[str, Any]:
        """As stored in the level and its snapshot."""
        return {"kind": self.kind.value, "target_id": self.target_id, "text": self.text}


@dataclass(frozen=True)
class Level:
    """One escalation level of a policy's target kind."""

    kind: TargetKind
    position: int  # 1-based order within the kind
    anchor: Anchor
    offset_seconds: int  # business seconds; negative is before the anchor
    recipients: tuple[Recipient, ...] = ()
    fallback: tuple[Recipient, ...] = ()  # when no relative is set (REQ-SLA-023 AC1)
    actions: tuple[Action, ...] = ()
    notify: bool = True

    @property
    def key(self) -> str:
        """Stable within a policy's snapshot: kind and position."""
        return f"{self.kind.value}:{self.position}"

    def as_json(self) -> dict[str, Any]:
        """As stored in the record's SLA snapshot (D-115 D7)."""
        return {
            "kind": self.kind.value,
            "position": self.position,
            "anchor": self.anchor.value,
            "offset_seconds": self.offset_seconds,
            "recipients": [r.as_json() for r in self.recipients],
            "fallback": [r.as_json() for r in self.fallback],
            "actions": [a.as_json() for a in self.actions],
            "notify": self.notify,
        }


def _recipient(value: Mapping[str, Any]) -> Recipient:
    raw = value.get("id")
    return Recipient(RecipientKind(value["kind"]), str(raw) if raw is not None else None)


def level_of(value: Mapping[str, Any]) -> Level:
    """A level from its stored JSON (snapshot) form."""
    return Level(
        kind=TargetKind(value["kind"]),
        position=int(value["position"]),
        anchor=Anchor(value["anchor"]),
        offset_seconds=int(value["offset_seconds"]),
        recipients=tuple(_recipient(r) for r in value.get("recipients", ())),
        fallback=tuple(_recipient(r) for r in value.get("fallback", ())),
        actions=tuple(
            Action(ActionKind(a["kind"]), a.get("target_id"), a.get("text"))
            for a in value.get("actions", ())
        ),
        notify=bool(value.get("notify", True)),
    )


Problems = list[tuple[str, str, dict[str, Any]]]


def level_problems(levels: Sequence[Level]) -> Problems:
    """What is wrong with a policy's levels: (field, code, params), empty when fine."""
    problems: Problems = []
    for kind in TargetKind:
        mine = [level for level in levels if level.kind is kind]
        if len(mine) > MAX_LEVELS:
            problems.append(("levels", "too_many_levels", {"max": MAX_LEVELS}))
        moments = [(level.anchor, level.offset_seconds) for level in mine]
        if len(set(moments)) != len(moments):
            problems.append(("levels", "levels_same_moment", {}))
    for index, level in enumerate(levels):
        problems.extend(_one_level(f"levels.{index}", level))
    return problems


def _one_level(field: str, level: Level) -> Problems:
    problems: Problems = []
    if abs(level.offset_seconds) > MAX_OFFSET_SECONDS:
        problems.append((f"{field}.offset_seconds", "offset_too_large", {}))
    if len(level.recipients) + len(level.fallback) > MAX_RECIPIENTS:
        problems.append(
            (f"{field}.recipients", "level_too_many_recipients", {"max": MAX_RECIPIENTS})
        )
    if len(level.actions) > MAX_ACTIONS:
        problems.append((f"{field}.actions", "level_too_many_actions", {"max": MAX_ACTIONS}))
    if level.notify and not level.recipients:
        problems.append((f"{field}.recipients", "required", {}))
    if not level.notify and not level.actions:
        problems.append((field, "level_does_nothing", {}))
    named = {RecipientKind.USER, RecipientKind.GROUP}
    if any(
        (who.kind in named) != (who.id is not None) for who in (*level.recipients, *level.fallback)
    ):
        problems.append((f"{field}.recipients", "recipient_shape", {}))
    problems.extend(_action_problems(field, level.actions))
    return problems


def _action_problems(field: str, actions: Sequence[Action]) -> Problems:
    problems: Problems = []
    for at, action in enumerate(actions):
        where = f"{field}.actions.{at}"
        reassign = action.kind in {ActionKind.REASSIGN_GROUP, ActionKind.REASSIGN_PERSON}
        if reassign and action.target_id is None:
            problems.append((f"{where}.target_id", "required", {}))
        if action.kind is ActionKind.ADD_NOTE and not (action.text or "").strip():
            problems.append((f"{where}.text", "required", {}))
        if action.text is not None and len(action.text) > NOTE_MAX:
            problems.append((f"{where}.text", "note_too_long", {"max": NOTE_MAX}))
    return problems


def level_used(level: Level, clock: TargetClock, warning_percent: int) -> int:
    """How much business time the clock has used when the level is due (may be negative)."""
    base = clock.target * warning_percent // 100 if level.anchor is Anchor.WARNING else clock.target
    return base + level.offset_seconds


def _by_hand_moment(level: Level, due: datetime, calendar: Calendar) -> datetime | None:
    if level.anchor is Anchor.WARNING:
        return None  # a date set by hand has no warning point
    if level.offset_seconds >= 0:
        return calendar.add(due, level.offset_seconds)
    return due - timedelta(seconds=-level.offset_seconds)


def level_moment(
    level: Level, clock: TargetClock, calendar: Calendar, warning_percent: int
) -> datetime | None:
    """When a waiting level runs; None while the clock is paused (held) or no longer open.

    A level already passed returns the moment it passed: the caller runs it at once.
    """
    if clock.state not in {TargetState.RUNNING, TargetState.BREACHED}:
        return None
    if clock.manual_due_at is not None:
        return _by_hand_moment(level, clock.manual_due_at, calendar)
    if clock.running_since is None:
        return None
    left = level_used(level, clock, warning_percent) - clock.used
    # Passed while the clock ran before (or the target shrank): due at once.
    return clock.running_since if left <= 0 else calendar.add(clock.running_since, left)
