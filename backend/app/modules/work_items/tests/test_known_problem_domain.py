"""What a requester is told of the problem behind their incident (REQ-PRB-075)."""

from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.portal import KnownProblem, known_problem


def test_req_prb_075_open_or_paused_is_being_worked_on_resolved_or_closed_is_fixed() -> None:
    assert known_problem(StatusCategory.OPEN.value) is KnownProblem.BEING_WORKED_ON
    assert known_problem(StatusCategory.PAUSED.value) is KnownProblem.BEING_WORKED_ON
    assert known_problem(StatusCategory.RESOLVED.value) is KnownProblem.FIXED
    assert known_problem(StatusCategory.CLOSED.value) is KnownProblem.FIXED


def test_req_prb_075_a_cancelled_or_merged_problem_says_nothing() -> None:
    assert known_problem(StatusCategory.CANCELED.value) is None
    assert known_problem(None) is None
