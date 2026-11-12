"""The bulk cancel takes the cancel transition, whatever order the moves come in.

A release in submission may also be rejected, and "submission_rejected" is canceled too: taking
the first move into canceled sometimes rejected instead of cancelling (lane B saw it in a merge
group, test_release_bulk_api line 132).
"""

from app.modules.work_items.domain.releases import RELEASE_MODEL
from app.modules.work_items.service.bulk import cancel_move
from app.modules.work_items.service.work_items import StageOffer


def _offer(to_status: str, *, allowed: bool = True) -> StageOffer:
    transition = next(
        t
        for t in RELEASE_MODEL.transitions
        if t.from_status == "submission_requested" and t.to_status == to_status
    )
    return StageOffer(
        transition=transition,
        to_stage=RELEASE_MODEL.status(to_status).stage,
        allowed=allowed,
        reason=None,
    )


def test_the_cancel_transition_wins_in_either_order() -> None:
    reject, cancel = _offer("submission_rejected"), _offer("closure_canceled")
    for moves in ([reject, cancel], [cancel, reject]):
        chosen = cancel_move(moves, RELEASE_MODEL)
        assert chosen is not None
        assert chosen.transition.to_status == "closure_canceled"


def test_a_cancel_you_may_not_make_is_a_skip_never_a_rejection() -> None:
    """Lane A's #452 review: no cancel right means the release is skipped, not rejected."""
    reject, cancel = _offer("submission_rejected"), _offer("closure_canceled", allowed=False)
    for moves in ([reject, cancel], [cancel, reject]):
        assert cancel_move(moves, RELEASE_MODEL) is None


def test_without_a_cancel_transition_an_allowed_move_into_canceled_is_taken() -> None:
    reject = _offer("submission_rejected")
    assert cancel_move([reject], RELEASE_MODEL) is reject
