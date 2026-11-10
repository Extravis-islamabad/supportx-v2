"""Changes' stage model (WP-045a S1; file 05 Appendix A, REQ-CHG-023..027, -031, -033)."""

import pytest

from app.modules.work_items.domain.changes import (
    CHANGE_MODEL,
    EMERGENCY_PATH,
    MAJOR_PATH,
    MINOR_PATH,
    STAGES,
    STANDARD_PATH,
)
from app.modules.work_items.domain.stages import (
    DEFAULT_PATH,
    MoveRefused,
    model_problems,
    plan_move,
)


def test_the_appendix_a_model_is_valid() -> None:
    assert model_problems(CHANGE_MODEL) == []


@pytest.mark.parametrize(
    ("path", "stages"),
    [
        (
            DEFAULT_PATH,
            ("submission", "planning", "cab_review", "implementation", "review", "closure"),
        ),
        (STANDARD_PATH, ("submission", "implementation", "review", "closure")),
        (MINOR_PATH, ("submission", "planning", "implementation", "review", "closure")),
        (MAJOR_PATH, STAGES),
        (EMERGENCY_PATH, ("submission", "cab_review", "implementation", "review", "closure")),
    ],
)
def test_req_chg_027_each_type_has_its_path(path: str, stages: tuple[str, ...]) -> None:
    assert CHANGE_MODEL.path(path).stages == stages


def test_req_chg_027_the_standard_review_is_optional() -> None:
    assert CHANGE_MODEL.path(STANDARD_PATH).optional == frozenset({"review"})


def test_req_chg_031_a_completing_status_moves_on_to_the_next_stage() -> None:
    move = plan_move(
        CHANGE_MODEL,
        current="planning_awaiting_approval",
        target="planning_plan_approved",
        path=DEFAULT_PATH,
        system=True,
    )
    assert move.landed.code == "cab_awaiting"
    on_minor = plan_move(
        CHANGE_MODEL,
        current="planning_awaiting_approval",
        target="planning_plan_approved",
        path=MINOR_PATH,
        system=True,
    )
    assert on_minor.landed.code == "implementation_scheduled"  # minor has no CAB


def test_approval_outcomes_are_set_by_the_approvals_code_only() -> None:
    with pytest.raises(MoveRefused) as refused:
        plan_move(
            CHANGE_MODEL,
            current="cab_awaiting",
            target="cab_approved",
            path=DEFAULT_PATH,
        )
    assert refused.value.code == "stage_status_system_only"


def test_a_rejected_cab_replans_only_where_there_is_planning() -> None:
    normal = {t.to_status for t in CHANGE_MODEL.moves_from("cab_rejected", DEFAULT_PATH)}
    emergency = {t.to_status for t in CHANGE_MODEL.moves_from("cab_rejected", EMERGENCY_PATH)}
    assert normal == {"planning_planning", "closure_closed"}
    assert emergency == {"closure_closed"}


def test_req_chg_033_cancel_until_implementation_is_in_progress_with_a_reason() -> None:
    before = CHANGE_MODEL.moves_from("implementation_scheduled", DEFAULT_PATH)
    cancel = next(t for t in before if t.to_status == "closure_canceled")
    assert cancel.permission == "cancel"
    assert cancel.reason_mode.value == "required"
    during = {
        t.to_status for t in CHANGE_MODEL.moves_from("implementation_in_progress", MAJOR_PATH)
    }
    assert "closure_canceled" not in during


def test_req_chg_031_backed_out_and_failed_go_to_the_review() -> None:
    for status in ("implementation_backed_out", "implementation_failed"):
        targets = {t.to_status for t in CHANGE_MODEL.moves_from(status, DEFAULT_PATH)}
        assert targets == {"review_in_review"}


def test_req_chg_005_a_type_has_one_model_and_its_path() -> None:
    from app.modules.work_items.domain.changes import (  # noqa: PLC0415 - this test only
        ChangeModel,
        model_of,
        path_of,
    )

    assert model_of("standard", None) is ChangeModel.STANDARD
    assert model_of("major", None) is ChangeModel.NORMAL
    assert model_of("emergency", {}) is ChangeModel.EMERGENCY
    assert model_of("datacentre_move", {"model": "emergency"}) is ChangeModel.EMERGENCY
    assert model_of("datacentre_move", {"model": "nonsense"}) is ChangeModel.NORMAL
    assert path_of("standard", ChangeModel.STANDARD) == STANDARD_PATH
    assert path_of("major", ChangeModel.NORMAL) == MAJOR_PATH
    assert path_of("datacentre_move", ChangeModel.NORMAL) == DEFAULT_PATH


def test_req_chg_006_only_the_system_pre_approves_at_creation() -> None:
    moved = plan_move(
        CHANGE_MODEL,
        current="submission_submitted",
        target="submission_accepted",
        path=STANDARD_PATH,
        system=True,
    )
    assert moved.landed.code == "implementation_scheduled"  # standard: no planning, no CAB
    with pytest.raises(MoveRefused):
        plan_move(
            CHANGE_MODEL,
            current="submission_submitted",
            target="submission_accepted",
            path=STANDARD_PATH,
        )


def test_req_chg_032_implementation_needs_its_matching_outcome() -> None:
    from app.modules.work_items.domain.changes import outcome_refusal  # noqa: PLC0415 - here only

    # No outcome (no schedule row yet, or one without an outcome): refused, never passed.
    assert outcome_refusal("implementation_implemented", None) == (
        "outcome_required",
        {"stage": "implementation"},
    )
    assert outcome_refusal("implementation_implemented", "failed") == (
        "outcome_mismatch",
        {"stage": "implementation", "outcome": "failed"},
    )
    assert outcome_refusal("implementation_implemented", "successful_with_issues") is None
    assert outcome_refusal("implementation_backed_out", "backed_out") is None
    assert outcome_refusal("implementation_in_progress", None) is None  # not a completing move
