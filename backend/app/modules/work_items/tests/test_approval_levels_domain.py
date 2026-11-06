"""A level's outcome under each rule (WP-058a s5; REQ-REL-031), the majority tie included."""

import pytest

from app.modules.work_items.domain.approvals import (
    ApprovalState,
    LevelOutcome,
    LevelRule,
    level_outcome,
)

P, A, R = ApprovalState.PENDING, ApprovalState.APPROVED, ApprovalState.REJECTED
W, N = ApprovalState.WITHDRAWN, ApprovalState.NOT_NEEDED


@pytest.mark.parametrize(
    ("rule", "states", "outcome"),
    [
        (LevelRule.ANY, [P, P, A], LevelOutcome.APPROVED),
        (LevelRule.ANY, [P, R], LevelOutcome.REJECTED),
        (LevelRule.ANY, [P, P], LevelOutcome.PENDING),
        (LevelRule.ALL, [A, A, P], LevelOutcome.PENDING),
        (LevelRule.ALL, [A, A, A], LevelOutcome.APPROVED),
        (LevelRule.ALL, [A, R, P], LevelOutcome.REJECTED),
        (LevelRule.MAJORITY, [A, A, P], LevelOutcome.APPROVED),  # 2 of 3
        (LevelRule.MAJORITY, [A, R, P], LevelOutcome.PENDING),  # still reachable
        (LevelRule.MAJORITY, [R, R, P], LevelOutcome.REJECTED),  # no longer reachable
        (LevelRule.MAJORITY, [A, A, R, R], LevelOutcome.REJECTED),  # the tie: an exact split
        (LevelRule.MAJORITY, [A, A, R, P], LevelOutcome.PENDING),  # 3 of 4 still possible
        (LevelRule.MAJORITY, [A, A, A, R], LevelOutcome.APPROVED),
        (LevelRule.MAJORITY, [A, W, N], LevelOutcome.APPROVED),  # withdrawn and not needed: out
        (LevelRule.ALL, [], LevelOutcome.PENDING),
    ],
)
def test_a_level_outcome_under_each_rule(
    rule: LevelRule, states: list[ApprovalState], outcome: LevelOutcome
) -> None:
    assert level_outcome(rule, states) is outcome


@pytest.mark.parametrize(
    ("states", "vote", "outcome"),
    [
        ([A, A, R, R], None, LevelOutcome.TIED),  # the split waits for the chair
        ([A, A, R, R], P, LevelOutcome.TIED),
        ([A, A, R, R], A, LevelOutcome.APPROVED),  # the chair breaks it (D-146)
        ([A, A, R, R], R, LevelOutcome.REJECTED),
        ([A, R, R, P], None, LevelOutcome.PENDING),  # a split is still possible
        ([R, R, R, P], None, LevelOutcome.REJECTED),  # not even a split is possible
        ([A, A, A, R], None, LevelOutcome.APPROVED),
        ([A, R, R], None, LevelOutcome.REJECTED),  # odd: no split, the chair has no say
    ],
)
def test_d146_the_chair_breaks_an_exact_split(
    states: list[ApprovalState], vote: ApprovalState | None, outcome: LevelOutcome
) -> None:
    assert level_outcome(LevelRule.MAJORITY, states, chair=True, chair_vote=vote) is outcome
    if outcome is LevelOutcome.TIED:  # with no chair the same split rejects, as before
        assert level_outcome(LevelRule.MAJORITY, states) is LevelOutcome.REJECTED
