"""Statuses, status categories and life cycles of work items (WP-020; ADR-026).

Pure domain code, no I/O. A tenant's statuses and transitions are *data* (the Appendix A defaults
of docs/specs/parity/01-work-items-incidents.md are seeded per tenant and are editable later),
but the rules are fixed here:

* every status has exactly one **category** (open, paused, resolved, closed, canceled) and the
  category, not the name, decides behaviour: the SLA clock pauses in `paused`, `closed` and
  `canceled` are final (REQ-INC-044);
* the status changes only through named **actions** allowed from the current status, on every
  path (REQ-INC-046); actions keep one fixed order whatever a tenant renames (REQ-WI-010);
* a transition can require a **reason** (REQ-INC-047).

`assign` and `unassign` are system actions: nobody presses them, assignment runs them
(REQ-INC-050). `undo_cancel` returns to the status the record had before it was canceled.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.shared.domain import InvalidTransition

REASON_TEXT_MAX = 500


class StatusCategory(StrEnum):
    """The fixed meaning of a status."""

    OPEN = "open"  # someone needs to act; SLA clock runs
    PAUSED = "paused"  # waiting on the requester or a third party; SLA clock paused
    RESOLVED = "resolved"  # fix given, waiting for confirmation
    CLOSED = "closed"  # finished (final)
    CANCELED = "canceled"  # not needed (final)


FINAL_CATEGORIES = frozenset({StatusCategory.CLOSED, StatusCategory.CANCELED})
DONE_CATEGORIES = FINAL_CATEGORIES | {StatusCategory.RESOLVED}


class WorkItemAction(StrEnum):
    """Status actions in the one order the UI shows them (system actions last, never shown)."""

    START_WORK = "start_work"
    WAIT_REQUESTER = "wait_requester"
    WAIT_THIRD_PARTY = "wait_third_party"
    RESUME = "resume"
    RESOLVE = "resolve"
    CLOSE = "close"
    REOPEN = "reopen"
    CANCEL = "cancel"
    UNDO_CANCEL = "undo_cancel"
    ASSIGN = "assign"  # system: a technician was set on a new record
    UNASSIGN = "unassign"  # system: the technician was removed from an assigned record


SYSTEM_ACTIONS = frozenset({WorkItemAction.ASSIGN, WorkItemAction.UNASSIGN})
USER_ACTIONS: tuple[WorkItemAction, ...] = tuple(
    a for a in WorkItemAction if a not in SYSTEM_ACTIONS
)


class ReasonMode(StrEnum):
    """Whether running a transition asks for a reason."""

    NONE = "none"
    OPTIONAL = "optional"
    REQUIRED = "required"


class ReasonList(StrEnum):
    """Pick lists of reasons (admin-editable values, seeded with defaults)."""

    PAUSE = "pause"
    THIRD_PARTY = "third_party"
    CANCEL = "cancel"
    REOPEN = "reopen"
    REASSIGN = "reassign"


@dataclass(frozen=True)
class StatusDef:
    """One status of a life cycle."""

    code: str
    category: StatusCategory
    colour: str
    system: bool = False  # set only by the system (e.g. merged), never offered as a target


@dataclass(frozen=True)
class TransitionDef:
    """`action` moves `from_status` to `to_status`; None means "the status before canceling"."""

    from_status: str
    action: WorkItemAction
    to_status: str | None
    reason_mode: ReasonMode = ReasonMode.NONE
    reason_list: ReasonList | None = None


class LifecycleError(ValueError):
    """A life cycle that can never work (unknown status, missing category, loop on final ...)."""


@dataclass(frozen=True)
class Lifecycle:
    """A validated set of statuses and transitions."""

    statuses: Mapping[str, StatusDef]
    transitions: Mapping[tuple[str, WorkItemAction], TransitionDef]

    @classmethod
    def build(
        cls, statuses: Iterable[StatusDef], transitions: Iterable[TransitionDef]
    ) -> "Lifecycle":
        """Validate and index; LifecycleError names what is wrong (REQ-WI-009 AC4)."""
        by_code = {s.code: s for s in statuses}
        index: dict[tuple[str, WorkItemAction], TransitionDef] = {}
        for t in transitions:
            if t.from_status not in by_code:
                msg = f"transition {t.action} starts at unknown status {t.from_status!r}"
                raise LifecycleError(msg)
            if t.to_status is not None and t.to_status not in by_code:
                msg = f"transition {t.action} leads to unknown status {t.to_status!r}"
                raise LifecycleError(msg)
            if t.to_status is None and t.action != WorkItemAction.UNDO_CANCEL:
                msg = f"only undo_cancel may return to the previous status, not {t.action}"
                raise LifecycleError(msg)
            if t.to_status is not None and by_code[t.to_status].system:
                msg = f"{t.to_status!r} is set by the system only"
                raise LifecycleError(msg)
            if t.reason_mode == ReasonMode.NONE and t.reason_list is not None:
                msg = f"{t.action} has a reason list but asks for no reason"
                raise LifecycleError(msg)
            if (t.from_status, t.action) in index:
                msg = f"{t.action} is defined twice from {t.from_status!r}"
                raise LifecycleError(msg)
            index[(t.from_status, t.action)] = t
        return cls(by_code, index)

    def category(self, status: str) -> StatusCategory:
        """The category of a status (KeyError for an unknown one: a data error)."""
        return self.statuses[status].category

    def actions_from(self, status: str) -> list[WorkItemAction]:
        """User actions allowed from `status`, in the fixed order."""
        return [a for a in USER_ACTIONS if (status, a) in self.transitions]

    def allows(self, status: str, action: WorkItemAction) -> bool:
        """Whether `action` is a transition from `status`."""
        return (status, action) in self.transitions

    def transition(self, status: str, action: WorkItemAction) -> TransitionDef:
        """The transition, or InvalidTransition (→ 409 invalid_transition)."""
        found = self.transitions.get((status, action))
        if found is None:
            raise InvalidTransition(status, action)
        return found

    def target(self, status: str, action: WorkItemAction, *, before_cancel: str | None) -> str:
        """Where `action` leads from `status` (undo_cancel: back to `before_cancel`)."""
        found = self.transition(status, action)
        if found.to_status is not None:
            return found.to_status
        if before_cancel is None or before_cancel not in self.statuses:
            raise InvalidTransition(status, action)
        return before_cancel


# --- the Appendix A defaults ----------------------------------------------------------------------


class DefaultStatus(StrEnum):
    """Codes of the seeded statuses (a tenant renames their labels, not their codes)."""

    NEW = "new"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    AWAITING_REQUESTER = "awaiting_requester"
    AWAITING_THIRD_PARTY = "awaiting_third_party"
    RESOLVED = "resolved"
    CLOSED = "closed"
    CANCELED = "canceled"
    MERGED = "merged"


S = DefaultStatus
A = WorkItemAction
DEFAULT_STATUSES: tuple[StatusDef, ...] = (
    StatusDef(S.NEW, StatusCategory.OPEN, "#1677ff"),
    StatusDef(S.ASSIGNED, StatusCategory.OPEN, "#2f54eb"),
    StatusDef(S.IN_PROGRESS, StatusCategory.OPEN, "#13c2c2"),
    StatusDef(S.AWAITING_REQUESTER, StatusCategory.PAUSED, "#faad14"),
    StatusDef(S.AWAITING_THIRD_PARTY, StatusCategory.PAUSED, "#fa8c16"),
    StatusDef(S.RESOLVED, StatusCategory.RESOLVED, "#52c41a"),
    StatusDef(S.CLOSED, StatusCategory.CLOSED, "#8c8c8c"),
    StatusDef(S.CANCELED, StatusCategory.CANCELED, "#bfbfbf"),
    StatusDef(S.MERGED, StatusCategory.CLOSED, "#bfbfbf", system=True),
)

_PAUSE = (ReasonMode.REQUIRED, ReasonList.PAUSE)
_THIRD = (ReasonMode.REQUIRED, ReasonList.THIRD_PARTY)
_CANCEL = (ReasonMode.REQUIRED, ReasonList.CANCEL)
_REOPEN = (ReasonMode.REQUIRED, ReasonList.REOPEN)


def _t(
    source: str, action: A, target: str | None, reason: tuple[ReasonMode, ReasonList] | None = None
) -> TransitionDef:
    mode, reason_list = reason or (ReasonMode.NONE, None)
    return TransitionDef(source, action, target, mode, reason_list)


DEFAULT_TRANSITIONS: tuple[TransitionDef, ...] = (
    _t(S.NEW, A.ASSIGN, S.ASSIGNED),
    _t(S.NEW, A.START_WORK, S.IN_PROGRESS),
    _t(S.NEW, A.RESOLVE, S.RESOLVED),
    _t(S.NEW, A.CANCEL, S.CANCELED, _CANCEL),
    _t(S.ASSIGNED, A.UNASSIGN, S.NEW),
    _t(S.ASSIGNED, A.START_WORK, S.IN_PROGRESS),
    _t(S.ASSIGNED, A.WAIT_REQUESTER, S.AWAITING_REQUESTER, _PAUSE),
    _t(S.ASSIGNED, A.WAIT_THIRD_PARTY, S.AWAITING_THIRD_PARTY, _THIRD),
    _t(S.ASSIGNED, A.RESOLVE, S.RESOLVED),
    _t(S.ASSIGNED, A.CANCEL, S.CANCELED, _CANCEL),
    _t(S.IN_PROGRESS, A.WAIT_REQUESTER, S.AWAITING_REQUESTER, _PAUSE),
    _t(S.IN_PROGRESS, A.WAIT_THIRD_PARTY, S.AWAITING_THIRD_PARTY, _THIRD),
    _t(S.IN_PROGRESS, A.RESOLVE, S.RESOLVED),
    _t(S.IN_PROGRESS, A.CANCEL, S.CANCELED, _CANCEL),
    _t(S.AWAITING_REQUESTER, A.RESUME, S.IN_PROGRESS),
    _t(S.AWAITING_REQUESTER, A.RESOLVE, S.RESOLVED),
    _t(S.AWAITING_REQUESTER, A.CANCEL, S.CANCELED, _CANCEL),
    _t(S.AWAITING_THIRD_PARTY, A.RESUME, S.IN_PROGRESS),
    _t(S.AWAITING_THIRD_PARTY, A.RESOLVE, S.RESOLVED),
    _t(S.AWAITING_THIRD_PARTY, A.CANCEL, S.CANCELED, _CANCEL),
    _t(S.RESOLVED, A.CLOSE, S.CLOSED),
    _t(S.RESOLVED, A.REOPEN, S.IN_PROGRESS, _REOPEN),
    _t(S.CLOSED, A.REOPEN, S.IN_PROGRESS, _REOPEN),
    TransitionDef(S.CANCELED, A.UNDO_CANCEL, None, ReasonMode.OPTIONAL),
)

DEFAULT_REASONS: Mapping[ReasonList, tuple[str, ...]] = {
    ReasonList.PAUSE: ("more_information", "confirmation", "access_or_availability", "other"),
    ReasonList.THIRD_PARTY: ("vendor", "other_team", "parts_or_delivery", "other"),
    ReasonList.CANCEL: (
        "logged_by_mistake",
        "solved_by_requester",
        "duplicate",
        "not_needed",
        "other",
    ),
    ReasonList.REOPEN: ("not_fixed", "came_back", "other"),
    ReasonList.REASSIGN: ("wrong_group", "needs_expertise", "workload", "other"),
}
OTHER_REASON = "other"


def default_lifecycle() -> Lifecycle:
    """The Appendix A life cycle (validated)."""
    return Lifecycle.build(DEFAULT_STATUSES, DEFAULT_TRANSITIONS)


# --- rules on top of a life cycle -----------------------------------------------------------------


def after_assignment(
    lifecycle: Lifecycle, status: str, *, had_technician: bool, has_technician: bool
) -> WorkItemAction | None:
    """The automatic status move an assignment causes, if any (REQ-INC-050).

    Setting the first technician runs `assign` where the life cycle has it (new → assigned);
    removing the technician runs `unassign` (assigned → new). Anything else keeps the status.
    """
    if has_technician and not had_technician and lifecycle.allows(status, WorkItemAction.ASSIGN):
        return WorkItemAction.ASSIGN
    if had_technician and not has_technician and lifecycle.allows(status, WorkItemAction.UNASSIGN):
        return WorkItemAction.UNASSIGN
    return None


def reason_problems(
    transition: TransitionDef,
    *,
    code: str | None,
    text: str | None,
    allowed_codes: Sequence[str],
) -> list[tuple[str, str]]:
    """(field, problem code) pairs for the reason given to a transition (REQ-INC-047).

    Required: a code from the list (if the transition has one) or text; "other" needs text.
    No reason allowed: none may be sent. Codes must come from the transition's list.
    """
    text = (text or "").strip() or None
    problems: list[tuple[str, str]] = []
    if transition.reason_mode == ReasonMode.NONE:
        if code is not None:
            problems.append(("reason_code", "not_allowed"))
        if text is not None:
            problems.append(("reason_text", "not_allowed"))
        return problems
    if text is not None and len(text) > REASON_TEXT_MAX:
        problems.append(("reason_text", "value_too_long"))
    if code is not None and (transition.reason_list is None or code not in allowed_codes):
        problems.append(("reason_code", "invalid_choice"))
    if transition.reason_mode == ReasonMode.REQUIRED:
        if transition.reason_list is not None and code is None:
            problems.append(("reason_code", "required"))
        elif transition.reason_list is None and text is None:
            problems.append(("reason_text", "required"))
    if code == OTHER_REASON and text is None:
        problems.append(("reason_text", "required"))
    return problems


@dataclass(frozen=True)
class PauseClock:
    """When the current pause started and how long earlier pauses lasted (whole seconds)."""

    paused_since: datetime | None
    paused_seconds: int


def move_pause_clock(
    clock: PauseClock, *, old: StatusCategory, new: StatusCategory, now: datetime
) -> PauseClock:
    """Start the pause clock on entering `paused`, add the pause up on leaving it (INC-044)."""
    if old != StatusCategory.PAUSED and new == StatusCategory.PAUSED:
        return PauseClock(now, clock.paused_seconds)
    if old == StatusCategory.PAUSED and new != StatusCategory.PAUSED and clock.paused_since:
        elapsed = int(max(0.0, (now - clock.paused_since).total_seconds()))
        return PauseClock(None, clock.paused_seconds + elapsed)
    return clock
