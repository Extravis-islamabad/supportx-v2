"""A request's approval stages in order, with parallel steps (WP-047a S2a; REQ-SR-029, -030)."""

import uuid

from app.modules.work_items.domain.approvals import (
    MAX_LEVELS,
    ApprovalState,
    ApproverOrigin,
    Assignment,
    LevelOutcome,
    LevelRule,
    RouteReason,
    level_outcome,
)
from app.modules.work_items.domain.request_stages import (
    Candidate,
    StagePlan,
    assign,
    ci_owner_targets,
    next_step,
    request_outcome,
    step_outcome,
    steps,
)

A, R, P = LevelOutcome.APPROVED, LevelOutcome.REJECTED, LevelOutcome.PENDING


def _plans(*groups: str | None) -> list[StagePlan]:
    return [StagePlan(n + 1, g) for n, g in enumerate(groups)]


def test_neighbours_sharing_a_parallel_group_form_one_step() -> None:
    plans = _plans(None, "finance", "finance", None, "legal", "legal", "finance")
    assert steps(plans) == [[1], [2, 3], [4], [5, 6], [7]]


def test_stages_run_in_order_and_a_parallel_step_opens_together() -> None:
    plans = _plans(None, "pair", "pair", None)
    assert next_step(plans, {}) == [1]
    assert next_step(plans, {1: A}) == [2, 3]
    assert next_step(plans, {1: A, 2: A}) == [3]  # the step waits for its other stage
    assert next_step(plans, {1: A, 2: A, 3: A}) == [4]
    assert next_step(plans, {1: A, 2: A, 3: A, 4: A}) is None
    assert request_outcome(plans, {1: A, 2: A, 3: A, 4: A}) is A


def test_one_rejection_in_a_parallel_step_rejects_the_request() -> None:
    """REQ-SR-030 AC2: the step fails on the first rejection (its others are withdrawn)."""
    plans = _plans("pair", "pair")
    assert step_outcome([1, 2], {1: R}) is R
    assert request_outcome(plans, {1: R}) is R
    assert request_outcome(plans, {1: A}) is P


def test_a_ten_stage_request_runs_to_the_end() -> None:
    """REQ-SR-029 AC4: ten stages; the staged record types keep their own cap of five."""
    plans = _plans(*([None] * 10))
    done: dict[int, LevelOutcome] = {}
    for n in range(1, 11):
        assert next_step(plans, done) == [n]
        done[n] = A
    assert request_outcome(plans, done) is A
    assert MAX_LEVELS == 5


def test_a_majority_tie_follows_the_tenants_tie_rule() -> None:
    """The coordinator's condition 1 (D-146): a tie rejects; with the chair it waits for them."""
    tie = [ApprovalState.APPROVED, ApprovalState.REJECTED]
    assert level_outcome(LevelRule.MAJORITY, tie) is R
    assert level_outcome(LevelRule.MAJORITY, tie, chair=True) is LevelOutcome.TIED
    assert (
        level_outcome(LevelRule.MAJORITY, tie, chair=True, chair_vote=ApprovalState.APPROVED) is A
    )
    # A tied stage keeps its step (and the request) waiting.
    assert step_outcome([1], {1: LevelOutcome.TIED}) is P


# --- assign -------------------------------------------------------------------------

REQUESTER = uuid.UUID("01900000-0000-7000-8000-0000000000c1")
ANN = uuid.UUID("01900000-0000-7000-8000-0000000000c2")
BACKUP = uuid.UUID("01900000-0000-7000-8000-0000000000c3")
NAMED, MANAGER = ApproverOrigin.NAMED, ApproverOrigin.MANAGER


def test_the_requester_never_approves_their_own_request() -> None:
    """Condition 2: left out (and audited by the caller), even when they were the only match."""
    found, dropped = assign(
        [Candidate(REQUESTER, NAMED), Candidate(ANN, MANAGER)],
        {REQUESTER: True, ANN: True},
        requester=REQUESTER,
        backup_id=None,
    )
    assert (found, dropped) == ([Assignment(ANN, MANAGER)], True)
    found, dropped = assign(
        [Candidate(REQUESTER, NAMED)], {REQUESTER: True}, requester=REQUESTER, backup_id=None
    )
    assert found == [
        Assignment(None, ApproverOrigin.ADMINISTRATORS, RouteReason.SELF_APPROVAL_BLOCKED)
    ]
    assert dropped


def test_nobody_goes_to_the_backup_then_the_administrators_with_the_reason() -> None:
    """Condition 3: never a stage stuck silently."""
    assert assign([], {BACKUP: True}, requester=REQUESTER, backup_id=BACKUP) == (
        [Assignment(BACKUP, ApproverOrigin.BACKUP, RouteReason.NO_APPROVER)],
        False,
    )
    assert assign([Candidate(ANN, NAMED)], {ANN: False}, requester=REQUESTER, backup_id=None) == (
        [Assignment(None, ApproverOrigin.ADMINISTRATORS, RouteReason.APPROVER_INACTIVE)],
        False,
    )
    # A backup who is the requester is never used.
    assert assign([], {REQUESTER: True}, requester=REQUESTER, backup_id=REQUESTER)[0] == [
        Assignment(None, ApproverOrigin.ADMINISTRATORS, RouteReason.NO_APPROVER)
    ]


def test_a_person_matched_twice_holds_one_approval() -> None:
    found, _ = assign(
        [Candidate(ANN, MANAGER), Candidate(ANN, NAMED)],
        {ANN: True},
        requester=REQUESTER,
        backup_id=None,
    )
    assert found == [Assignment(ANN, MANAGER)]


def test_a_ci_owner_person_approves_alone_and_the_group_only_without_one() -> None:
    """Lane B's #582 question, named: the person when there is one, else the owner group."""
    group = uuid.UUID("01900000-0000-7000-8000-0000000000d1")
    other = uuid.UUID("01900000-0000-7000-8000-0000000000d2")
    assert ci_owner_targets([(ANN, group)]) == ([ANN], [])
    assert ci_owner_targets([(None, group)]) == ([], [group])
    assert ci_owner_targets([(ANN, None), (None, other), (ANN, group)]) == ([ANN], [other])
    assert ci_owner_targets([(None, None)]) == ([], [])
