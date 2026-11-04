"""The problem life cycle (WP-044a s1; REQ-PRB-023, Appendix A; no I/O)."""

import pytest

from app.modules.work_items.domain.lifecycle import (
    PROBLEM_STATUSES,
    Lifecycle,
    LifecycleError,
    StatusCategory,
    TransitionDef,
    problem_lifecycle,
)
from app.modules.work_items.domain.lifecycle import (
    DefaultStatus as S,
)
from app.modules.work_items.domain.lifecycle import (
    ProblemStatus as P,
)
from app.modules.work_items.domain.lifecycle import (
    WorkItemAction as A,
)
from app.modules.work_items.domain.types import PROBLEM, TYPES, WorkItemTypeCode
from app.shared.domain import InvalidTransition


def test_the_appendix_statuses_and_categories() -> None:
    life = problem_lifecycle()
    assert {code: life.category(code) for code in life.statuses} == {
        "new": StatusCategory.OPEN,
        "assigned": StatusCategory.OPEN,
        "investigating": StatusCategory.OPEN,
        "root_cause_found": StatusCategory.OPEN,
        "awaiting_fix": StatusCategory.OPEN,
        "on_hold": StatusCategory.PAUSED,
        # the guided life cycle's steps, on the same statuses table (REQ-PRB-025)
        "gathering_facts": StatusCategory.OPEN,
        "why_analysis": StatusCategory.OPEN,
        "cause_confirmed": StatusCategory.OPEN,
        "fix_planned": StatusCategory.OPEN,
        "resolved": StatusCategory.RESOLVED,
        "fix_verified": StatusCategory.RESOLVED,
        "in_review": StatusCategory.RESOLVED,
        "closed": StatusCategory.CLOSED,
        "canceled": StatusCategory.CANCELED,
        "merged": StatusCategory.CLOSED,
    }
    assert life.statuses["merged"].system  # set by merge only


def test_the_appendix_transitions() -> None:
    life = problem_lifecycle()

    def to(status: str, action: A) -> str:
        return life.target(status, action, before_cancel=None, before_pause=None)

    assert to(S.NEW, A.INVESTIGATE) == P.INVESTIGATING
    assert to(S.NEW, A.ASSIGN) == S.ASSIGNED  # automatic when an owner is set
    assert to(S.ASSIGNED, A.UNASSIGN) == S.NEW
    assert to(P.INVESTIGATING, A.CONFIRM_ROOT_CAUSE) == P.ROOT_CAUSE_FOUND
    assert to(P.ROOT_CAUSE_FOUND, A.INVESTIGATE) == P.INVESTIGATING  # the cause was rejected
    assert to(P.ROOT_CAUSE_FOUND, A.AWAIT_FIX) == P.AWAITING_FIX
    assert to(P.ROOT_CAUSE_FOUND, A.CLOSE) == S.CLOSED  # accepted, no fix
    assert to(P.AWAITING_FIX, A.INVESTIGATE) == P.INVESTIGATING  # the fix failed
    assert to(P.AWAITING_FIX, A.RESOLVE) == S.RESOLVED
    assert to(S.RESOLVED, A.REOPEN) == P.INVESTIGATING
    assert to(S.CLOSED, A.REOPEN) == P.INVESTIGATING
    # Not in the table: never offered.
    for status, action in (
        (S.NEW, A.RESOLVE),
        (S.NEW, A.HOLD),
        (P.INVESTIGATING, A.AWAIT_FIX),
        (S.RESOLVED, A.HOLD),
    ):
        with pytest.raises(InvalidTransition):
            life.transition(status, action)
    assert life.transition(S.NEW, A.CANCEL).reason_mode == "required"
    assert life.transition(P.INVESTIGATING, A.HOLD).reason_mode == "required"


def test_on_hold_resumes_where_it_was_put_on_hold() -> None:
    life = problem_lifecycle()
    for before in (S.ASSIGNED, P.INVESTIGATING, P.AWAITING_FIX):
        assert life.target(P.ON_HOLD, A.RESUME, before_cancel=None, before_pause=before) == before
    with pytest.raises(InvalidTransition):  # nothing remembered: refused, never guessed
        life.target(P.ON_HOLD, A.RESUME, before_cancel=None, before_pause=None)
    with pytest.raises(InvalidTransition):  # a system status is never resumed into
        life.target(P.ON_HOLD, A.RESUME, before_cancel=None, before_pause=S.MERGED)
    assert life.target(S.CANCELED, A.UNDO_CANCEL, before_cancel=P.AWAITING_FIX) == P.AWAITING_FIX


def test_only_resume_and_undo_cancel_may_return() -> None:
    with pytest.raises(LifecycleError):
        Lifecycle.build(PROBLEM_STATUSES, [TransitionDef(P.INVESTIGATING, A.HOLD, None)])


def test_problems_are_a_registered_type() -> None:
    assert TYPES[WorkItemTypeCode.PROBLEM] is PROBLEM
    assert (PROBLEM.path, PROBLEM.default_prefix, PROBLEM.feature) == ("problems", "PRB", "problem")
    assert PROBLEM.counter_key == "WI_PROBLEM"
    assert PROBLEM.permission("edit") == "problems.edit"


def test_each_type_lists_only_its_own_actions() -> None:
    from app.modules.work_items.domain.lifecycle import default_lifecycle  # noqa: PLC0415

    incident = default_lifecycle().used_actions()
    assert A.INVESTIGATE not in incident  # an incident never offers a problem's actions
    assert A.HOLD not in incident
    problem_actions = problem_lifecycle().used_actions()
    assert A.START_WORK not in problem_actions
    assert A.WAIT_REQUESTER not in problem_actions
    assert problem_actions[:2] == [A.INVESTIGATE, A.CONFIRM_ROOT_CAUSE]


def test_the_guided_life_cycle_walks_the_analysis_steps() -> None:
    """REQ-PRB-025, Appendix A: facts → why → cause confirmed → fix planned → verified → review."""
    from app.modules.work_items.domain.lifecycle import guided_problem_lifecycle  # noqa: PLC0415
    from app.modules.work_items.domain.types import GUIDED_ANALYSIS  # noqa: PLC0415

    assert set(PROBLEM.lifecycles) == {"standard", GUIDED_ANALYSIS}
    life = guided_problem_lifecycle()
    status = "new"
    steps = ["investigate", "analyse", "confirm_root_cause", "await_fix", "resolve"]
    walked = []
    for step in steps:
        status = life.target(status, A(step), before_cancel=None)
        walked.append(status)
    assert walked == [
        "gathering_facts",
        "why_analysis",
        "cause_confirmed",
        "fix_planned",
        "fix_verified",
    ]
    assert not life.allows("fix_verified", A.CLOSE)  # the review comes first
    assert life.target("fix_verified", A.START_REVIEW, before_cancel=None) == ("in_review")
    assert life.allows("in_review", A.CLOSE)
    # Back to the analysis when the cause is rejected or the fix fails.
    for status in ("cause_confirmed", "fix_planned"):
        assert life.target(status, A.INVESTIGATE, before_cancel=None) == "why_analysis"
    # The standard life cycle never reaches a guided step.
    standard = problem_lifecycle()
    reached = {t.to_status for t in standard.transitions.values()}
    assert not reached & {"gathering_facts", "why_analysis", "fix_verified", "in_review"}
