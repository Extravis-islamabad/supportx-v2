"""The stage engine's rules (ADR-041; REQ-WI-026, REQ-REL-014..017), on releases' seeds. No I/O."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.releases import EMERGENCY_PATH, RELEASE_MODEL, STAGES
from app.modules.work_items.domain.stages import (
    DEFAULT_PATH,
    Entry,
    MoveRefused,
    PathDef,
    RailState,
    StageDef,
    StagedStatusDef,
    StageModel,
    StageModelError,
    StatusTransitionDef,
    plan_move,
    rail,
)

M = RELEASE_MODEL
T0 = datetime(2026, 11, 5, 9, tzinfo=UTC)


def test_req_rel_014_every_status_has_a_stage_and_a_category_and_one_completing_per_stage() -> None:
    assert [s.code for s in M.stages] == list(STAGES)
    for stage in STAGES[:-1]:  # closure ends the release: no completing status
        assert sum(s.completing for s in M.statuses_of(stage)) == 1
    assert all(isinstance(s.category, StatusCategory) for s in M.statuses)


def test_a_model_without_a_completing_status_or_with_unknown_names_is_refused() -> None:
    with pytest.raises(StageModelError) as refused:
        StageModel(
            stages=(StageDef("a"), StageDef("b")),
            statuses=(
                StagedStatusDef("a_open", "a", StatusCategory.OPEN, "#000000"),
                StagedStatusDef("b_done", "b", StatusCategory.CLOSED, "#000000"),
            ),
            paths=(PathDef("default", ("b", "a")),),
            transitions=(StatusTransitionDef("a_open", "nowhere"),),
        )
    assert set(refused.value.problems) == {
        "stage_needs_one_completing_status:a",
        "path_out_of_order:default",
        "transition_with_unknown_status:a_open->nowhere",
    }


def test_req_rel_016_only_listed_moves_inside_a_stage() -> None:
    move = plan_move(M, current="build_in_progress", target="build_backed_out", path=DEFAULT_PATH)
    assert (move.landed.code, move.entered) == ("build_backed_out", ())
    with pytest.raises(MoveRefused) as refused:
        plan_move(
            M, current="deployment_scheduled", target="deployment_deployed", path=DEFAULT_PATH
        )
    assert refused.value.code == "stage_move_not_allowed"


def test_reaching_the_completing_status_moves_on_to_the_next_stage_in_one_move() -> None:
    move = plan_move(M, current="build_in_progress", target="build_completed", path=DEFAULT_PATH)
    assert (move.target.code, move.landed.code, move.entered) == (
        "build_completed",
        "testing_in_progress",
        ("testing",),
    )
    # The emergency path has no training: deployed moves straight on to review.
    deployed = plan_move(
        M, current="deployment_in_progress", target="deployment_deployed", path=EMERGENCY_PATH
    )
    assert (deployed.landed.code, deployed.entered) == ("review_in_progress", ("review",))


def test_req_rel_017_backward_moves_go_to_another_stage() -> None:
    move = plan_move(M, current="testing_failed", target="build_in_progress", path=DEFAULT_PATH)
    assert move.entered == ("build",)


def test_approval_outcomes_are_set_by_the_system_only() -> None:
    with pytest.raises(MoveRefused) as refused:
        plan_move(
            M,
            current="planning_waiting_approval",
            target="planning_plan_approved",
            path=DEFAULT_PATH,
        )
    assert refused.value.code == "stage_status_system_only"
    approved = plan_move(
        M,
        current="planning_waiting_approval",
        target="planning_plan_approved",
        path=DEFAULT_PATH,
        system=True,
    )
    assert approved.landed.code == "build_in_progress"


def test_cancel_from_any_stage_before_closure_needs_a_reason_and_its_permission() -> None:
    move = plan_move(M, current="testing_in_progress", target="closure_canceled", path=DEFAULT_PATH)
    assert move.transition.reason_mode == "required"
    assert move.transition.permission == "cancel"
    with pytest.raises(MoveRefused):
        plan_move(M, current="closure_closed", target="closure_canceled", path=DEFAULT_PATH)


def test_stages_off_the_path_are_never_offered() -> None:
    offered = {t.to_status for t in M.moves_from("submission_requested", EMERGENCY_PATH)}
    assert "planning_in_planning" not in offered
    assert M.next_stage("submission", EMERGENCY_PATH) == "build"


def test_the_rail_shows_done_current_skipped_and_future_and_keeps_every_round() -> None:
    entries = [
        Entry("submission", T0, T0 + timedelta(hours=1)),
        Entry("build", T0 + timedelta(hours=1), T0 + timedelta(hours=2)),  # planning skipped
        Entry("testing", T0 + timedelta(hours=2), T0 + timedelta(hours=3)),
        Entry("build", T0 + timedelta(hours=3), None),  # back to build: a second round
    ]
    states = {
        s.stage: (s.state, len(s.entries))
        for s in rail(M, path=DEFAULT_PATH, current="build", entries=entries)
    }
    assert states["submission"] == (RailState.DONE, 1)
    assert states["planning"] == (RailState.SKIPPED, 0)
    assert states["build"] == (RailState.CURRENT, 2)
    assert states["testing"] == (RailState.DONE, 1)
    assert states["deployment"] == (RailState.FUTURE, 0)
    emergency = [s.stage for s in rail(M, path=EMERGENCY_PATH, current="build", entries=entries)]
    assert "planning" not in emergency  # off the path: not shown at all
