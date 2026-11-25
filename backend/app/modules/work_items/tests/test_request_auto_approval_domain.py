"""Automatic approval of a request stage (WP-047a S2b; REQ-SR-033): pure rules, no I/O."""

import uuid

import pytest

from app.modules.work_items.domain import stage_snapshot
from app.modules.work_items.domain.approvals import (
    ApprovalState,
    ApproverOrigin,
    Assignment,
    AutoReason,
    LevelRule,
)
from app.modules.work_items.domain.request_stages import (
    first_matching_rule,
    matched_keys,
    open_with_earlier,
)

ANN, BOB, CAT = (uuid.UUID(f"01900000-0000-7000-8000-00000000000{n}") for n in (1, 2, 3))


def _named(*people: uuid.UUID) -> list[Assignment]:
    return [Assignment(p, ApproverOrigin.NAMED) for p in people]


def test_ac1_someone_who_approved_stage_1_is_not_asked_again() -> None:
    """AC1: approved automatically, naming stage 1; under `any` the others are not needed."""
    opened = open_with_earlier(_named(ANN, BOB), LevelRule.ANY, {ANN: 1})
    assert [(o.assignment.approver_id, o.state) for o in opened] == [
        (ANN, ApprovalState.APPROVED),
        (BOB, ApprovalState.NOT_NEEDED),
    ]
    assert (opened[0].auto_reason, opened[0].auto_ref) == (AutoReason.APPROVED_EARLIER, 1)
    assert opened[1].auto_reason is None


def test_under_all_only_their_own_vote_counts_and_the_others_are_still_asked() -> None:
    opened = open_with_earlier(_named(ANN, BOB), LevelRule.ALL, {ANN: 2})
    assert [o.state for o in opened] == [ApprovalState.APPROVED, ApprovalState.PENDING]


@pytest.mark.parametrize(
    ("earlier", "states"),
    [
        ({ANN: 1}, [ApprovalState.APPROVED, ApprovalState.PENDING, ApprovalState.PENDING]),
        (
            {ANN: 1, BOB: 1},
            [ApprovalState.APPROVED, ApprovalState.APPROVED, ApprovalState.NOT_NEEDED],
        ),
    ],
)
def test_under_majority_it_decides_only_once_a_majority_is_there(
    earlier: dict[uuid.UUID, int], states: list[ApprovalState]
) -> None:
    opened = open_with_earlier(_named(ANN, BOB, CAT), LevelRule.MAJORITY, earlier)
    assert [o.state for o in opened] == states


def test_nobody_approved_earlier_leaves_every_approval_waiting() -> None:
    opened = open_with_earlier(_named(ANN, BOB), LevelRule.ANY, {})
    assert {o.state for o in opened} == {ApprovalState.PENDING}


def test_the_administrators_are_never_approved_automatically() -> None:
    admins = [Assignment(None, ApproverOrigin.ADMINISTRATORS)]
    assert open_with_earlier(admins, LevelRule.ANY, {ANN: 1})[0].state is ApprovalState.PENDING


def test_the_first_rule_that_holds_decides_and_names_only_its_keys() -> None:
    small = {"field": "quantity", "op": "in", "value": [1, 2]}
    member = {"field": "requester_groups", "op": "eq", "value": str(CAT)}
    values = {"quantity": 5, "requester_groups": [str(CAT)], "model": "air"}
    assert first_matching_rule([small, member], values) == 2
    assert first_matching_rule([small], values) is None
    both = {"and": [member, {"field": "model", "op": "eq", "value": "air"}]}
    assert matched_keys(both) == ["model", "requester_groups"]  # keys, never the values


def test_the_snapshot_keeps_the_resolved_switch_and_the_rules() -> None:
    stage = stage_snapshot.SnapStage(
        approvers=(stage_snapshot.SnapApprover("person", ANN),),
        auto_earlier=True,
        auto_rules=(
            stage_snapshot.SnapRule(
                {"en": "Small orders"}, {"field": "quantity", "op": "eq", "value": 1}
            ),
        ),
    )
    stored = stage_snapshot.to_json([stage])
    assert stored["stages"][0]["auto_earlier"] is True
    assert stage_snapshot.from_json(stored) == (stage,)


def test_a_snapshot_from_before_s2b_reads_with_both_off() -> None:
    stored = {"v": 1, "stages": [{"approvers": [{"kind": "requested_for_manager"}]}]}
    (stage,) = stage_snapshot.from_json(stored)
    assert (stage.auto_earlier, stage.auto_rules) == (False, ())


@pytest.mark.parametrize(
    "bad",
    [
        {"auto_earlier": "yes"},
        {"auto_rules": {"name": {"en": "x"}}},
        {"auto_rules": [{"name": {"en": "x"}}]},
        {"auto_rules": [{"name": "x", "condition": {}}]},
    ],
)
def test_a_badly_shaped_automatic_part_is_refused(bad: dict[str, object]) -> None:
    stored = {"v": 1, "stages": [{"approvers": [], **bad}]}
    with pytest.raises(stage_snapshot.SnapshotShapeError):
        stage_snapshot.from_json(stored)
