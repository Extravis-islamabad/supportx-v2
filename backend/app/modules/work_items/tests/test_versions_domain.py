"""A draft life cycle version's problems (ADR-049 §6; REQ-INC-049 AC1), without I/O."""

from app.modules.work_items.domain.lifecycle import (
    DEFAULT_STATUSES,
    DEFAULT_TRANSITIONS,
    ReasonList,
    ReasonMode,
    StatusCategory,
    StatusDef,
    TransitionDef,
    WorkItemAction,
)
from app.modules.work_items.domain.versions import Move, Problem, VersionProblem, validate

A = WorkItemAction
ALLOWED = frozenset({"incidents.close", "incidents.cancel"})


def _check(
    moves: list[Move], statuses: tuple[StatusDef, ...] = DEFAULT_STATUSES
) -> list[VersionProblem]:
    return validate(statuses, moves, custom_keys=["cost_centre"], allowed_permissions=ALLOWED)


def _shipped() -> list[Move]:
    return [Move(t) for t in DEFAULT_TRANSITIONS]


def test_the_shipped_incident_life_cycle_has_no_problems() -> None:
    assert _check(_shipped()) == []


def test_ac1_a_status_with_no_way_out_is_named() -> None:
    """Every move out of "awaiting the requester" removed: the draft names that status."""
    paused = [m for m in _shipped() if m.transition.from_status != "awaiting_requester"]
    problems = _check(paused)
    assert VersionProblem(Problem.NO_WAY_OUT, {"status": "awaiting_requester"}) in problems


def test_a_final_status_needs_no_way_out() -> None:
    closed = [m for m in _shipped() if m.transition.from_status != "closed"]
    assert all(p.code is not Problem.NO_WAY_OUT for p in _check(closed))


def test_unknown_statuses_unsupported_returns_and_system_targets_are_named() -> None:
    statuses = (
        *DEFAULT_STATUSES,
        StatusDef("merged_away", StatusCategory.CLOSED, "#999999", system=True),
    )
    moves = [
        *_shipped(),
        Move(TransitionDef("new", A.START_WORK, "nowhere")),
        Move(TransitionDef("in_progress", A.CLOSE, None)),
        Move(TransitionDef("assigned", A.CANCEL, "merged_away")),
    ]
    problems = _check(moves, statuses)
    assert VersionProblem(Problem.UNKNOWN_STATUS, {"status": "nowhere"}) in problems
    assert VersionProblem(Problem.RETURN_NOT_ALLOWED, {"action": "close"}) in problems
    assert (
        VersionProblem(Problem.SYSTEM_STATUS, {"status": "merged_away", "action": "cancel"})
        in problems
    )


def test_a_reason_list_without_a_prompt_is_named() -> None:
    moves = [
        *[m for m in _shipped() if m.transition.action is not A.CANCEL],
        Move(TransitionDef("new", A.CANCEL, "canceled", ReasonMode.NONE, ReasonList.CANCEL)),
    ]
    assert VersionProblem(
        Problem.REASON_LIST_WITHOUT_PROMPT, {"action": "cancel", "status": "new"}
    ) in _check(moves)


def test_required_fields_must_be_real_fields() -> None:
    moves = [
        *[m for m in _shipped() if m.transition.action is not A.RESOLVE],
        *[
            Move(m.transition, required_fields=("category_id", "custom.cost_centre", "shoe_size"))
            for m in _shipped()
            if m.transition.action is A.RESOLVE
        ],
    ]
    problems = _check(moves)
    assert VersionProblem(Problem.UNKNOWN_FIELD, {"field": "shoe_size"}) in problems
    assert all(p.params.get("field") != "category_id" for p in problems)
    assert all(p.params.get("field") != "custom.cost_centre" for p in problems)


def test_an_extra_right_must_be_one_the_type_allows() -> None:
    """Never an administrator-only right such as managing roles (ADR-049 §5)."""
    moves = [
        *[m for m in _shipped() if m.transition.action is not A.CLOSE],
        *[
            Move(m.transition, permission="roles.manage")
            for m in _shipped()
            if m.transition.action is A.CLOSE
        ],
    ]
    assert VersionProblem(Problem.PERMISSION_NOT_ALLOWED, {"permission": "roles.manage"}) in _check(
        moves
    )
    allowed = [
        Move(m.transition, permission="incidents.close" if m.transition.action is A.CLOSE else None)
        for m in _shipped()
    ]
    assert _check(allowed) == []


def test_an_empty_life_cycle_is_a_problem() -> None:
    assert _check([]) == [VersionProblem(Problem.NO_MOVES)]
