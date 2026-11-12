"""Life cycle versions (ADR-049): one versioning model for action-based and staged types.

A life cycle (a type's transition set: "standard", or one a template names) has numbered
versions. A draft is edited; a published one never changes (an edit makes the next draft);
a retired one stays readable for the records still on it. Every record runs on the version it
was made on until an administrator migrates it (REQ-INC-049 AC3).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.modules.work_items.domain.closure import rule_field_problems
from app.modules.work_items.domain.lifecycle import (
    FINAL_CATEGORIES,
    RETURNING_ACTIONS,
    SYSTEM_ACTIONS,
    ReasonMode,
    StatusDef,
    TransitionDef,
)

FIRST_VERSION = 1


class VersionState(StrEnum):
    """Where a life cycle version stands."""

    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


# Records may run on these (a retired version keeps working for the records still on it).
RUNNABLE_STATES = frozenset({VersionState.PUBLISHED, VersionState.RETIRED})


class Problem(StrEnum):
    """What keeps a draft from publishing; each names exactly what to fix (ADR-049 §6)."""

    NO_WAY_OUT = "status_no_way_out"  # {status}: not final, and no move leaves it (AC1)
    UNKNOWN_STATUS = "unknown_status"  # {status}
    RETURN_NOT_ALLOWED = "return_not_allowed"  # {action}: only undo cancel and resume go back
    SYSTEM_STATUS = "system_status_target"  # {status, action}: set by the system only
    REASON_LIST_WITHOUT_PROMPT = "reason_list_without_prompt"  # {action, status}
    UNKNOWN_FIELD = "required_field_unknown"  # {field}
    PERMISSION_NOT_ALLOWED = "permission_not_allowed"  # {permission}
    NO_MOVES = "no_moves"  # an empty life cycle


@dataclass(frozen=True)
class Move:
    """One move of a draft: the transition and what ADR-049 adds to it per version."""

    transition: TransitionDef
    permission: str | None = None
    required_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class VersionProblem:
    """One problem, by code and the names it concerns (never a free text)."""

    code: Problem
    params: dict[str, str] = field(default_factory=dict)

    def as_json(self) -> dict[str, object]:
        """As stored on the version and returned to the designer."""
        return {"code": self.code.value, "params": dict(self.params)}


def validate(  # noqa: C901, PLR0912 - one check per rule, flat
    statuses: Iterable[StatusDef],
    moves: Sequence[Move],
    *,
    custom_keys: Iterable[str],
    allowed_permissions: frozenset[str],
) -> list[VersionProblem]:
    """Every problem of a draft; none means it may publish (ADR-049 §6, REQ-INC-049 AC1).

    `allowed_permissions`: the rights a move may additionally require (the type's own rights in
    the catalogue; never an administrator-only one).
    """
    by_code = {s.code: s for s in statuses}
    found: list[VersionProblem] = []

    def add(code: Problem, **params: str) -> None:
        problem = VersionProblem(code, params)
        if problem not in found:
            found.append(problem)

    if not moves:
        add(Problem.NO_MOVES)
    leaving: set[str] = set()
    used: set[str] = set()
    for move in moves:
        t = move.transition
        action = t.action.value
        for status in (t.from_status, t.to_status):
            if status is not None and status not in by_code:
                add(Problem.UNKNOWN_STATUS, status=status)
        if t.from_status in by_code:
            used.add(t.from_status)
            leaving.add(t.from_status)
        if t.to_status is None and t.action not in RETURNING_ACTIONS:
            add(Problem.RETURN_NOT_ALLOWED, action=action)
        if t.to_status in by_code:
            used.add(t.to_status)
            if by_code[t.to_status].system and t.action not in SYSTEM_ACTIONS:
                add(Problem.SYSTEM_STATUS, status=t.to_status, action=action)
        if t.reason_mode == ReasonMode.NONE and t.reason_list is not None:
            add(Problem.REASON_LIST_WITHOUT_PROMPT, action=action, status=t.from_status)
        for name in rule_field_problems(move.required_fields, custom_keys):
            add(Problem.UNKNOWN_FIELD, field=name)
        if move.permission is not None and move.permission not in allowed_permissions:
            add(Problem.PERMISSION_NOT_ALLOWED, permission=move.permission)
    for status in sorted(used - leaving):
        if by_code[status].category not in FINAL_CATEGORIES:
            add(Problem.NO_WAY_OUT, status=status)
    return found


__all__ = [
    "FIRST_VERSION",
    "RUNNABLE_STATES",
    "Move",
    "Problem",
    "VersionProblem",
    "VersionState",
    "validate",
]
