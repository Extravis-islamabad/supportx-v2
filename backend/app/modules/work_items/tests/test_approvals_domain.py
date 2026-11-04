"""The approval engine's pure rules (WP-030 s2; REQ-SR-022, -023, -027, -028)."""

import uuid

from app.modules.work_items.domain.approvals import (
    ApproverOrigin,
    ApproverSpec,
    Assignment,
    Decision,
    Person,
    RouteReason,
    StageInput,
    blocked_for_self,
    decision_problems,
    resolve,
)

REQUESTER, FOR, MANAGER, NAMED, BACKUP = (uuid.uuid4() for _ in range(5))
MANAGER_STAGE = (ApproverSpec(manager_of_requested_for=True),)


def stage(**over: object) -> StageInput:
    values: dict[str, object] = {
        "approvers": MANAGER_STAGE,
        "backup_id": None,
        "self_approval": False,
        "requested_by": REQUESTER,
        "requested_for": FOR,
        "manager_id": MANAGER,
    }
    values.update(over)
    return StageInput(**values)  # type: ignore[arg-type]  # test helper: keys checked above


def everyone(*inactive: uuid.UUID) -> dict[uuid.UUID, Person]:
    ids = (REQUESTER, FOR, MANAGER, NAMED, BACKUP)
    return {i: Person(i, active=i not in inactive) for i in ids}


def test_the_manager_of_the_person_it_is_for_approves() -> None:
    assert resolve(stage(), everyone()) == [Assignment(MANAGER, ApproverOrigin.MANAGER)]


def test_named_approvers_are_deduplicated_and_kept_in_order() -> None:
    specs = (
        ApproverSpec(manager_of_requested_for=False, person_id=NAMED),
        ApproverSpec(manager_of_requested_for=True),
        ApproverSpec(manager_of_requested_for=False, person_id=NAMED),
    )
    found = resolve(stage(approvers=specs), everyone())
    assert [a.approver_id for a in found] == [NAMED, MANAGER]


def test_no_manager_goes_to_the_backup_then_the_administrators() -> None:
    """REQ-SR-023 AC1: never nobody; the reason stays on the approval."""
    backup = resolve(stage(manager_id=None, backup_id=BACKUP), everyone())
    assert backup == [Assignment(BACKUP, ApproverOrigin.BACKUP, RouteReason.NO_MANAGER)]
    admins = resolve(stage(manager_id=None), everyone())
    assert admins == [Assignment(None, ApproverOrigin.ADMINISTRATORS, RouteReason.NO_MANAGER)]
    gone = resolve(stage(manager_id=None, backup_id=BACKUP), everyone(BACKUP))
    assert gone[0].origin is ApproverOrigin.ADMINISTRATORS


def test_an_inactive_approver_is_passed_over() -> None:
    found = resolve(stage(), everyone(MANAGER))
    assert found == [Assignment(None, ApproverOrigin.ADMINISTRATORS, RouteReason.APPROVER_INACTIVE)]


def test_nobody_approves_their_own_request_unless_the_item_allows_it() -> None:
    """REQ-SR-027 AC1, AC3."""
    mine = (ApproverSpec(manager_of_requested_for=False, person_id=REQUESTER),)
    blocked = resolve(stage(approvers=mine, backup_id=BACKUP), everyone())
    assert blocked == [Assignment(BACKUP, ApproverOrigin.BACKUP, RouteReason.SELF_APPROVAL_BLOCKED)]
    allowed = resolve(stage(approvers=mine, self_approval=True), everyone())
    assert allowed == [Assignment(REQUESTER, ApproverOrigin.NAMED)]
    # The backup is never the requester either.
    assert resolve(stage(approvers=mine, backup_id=FOR), everyone())[0].approver_id is None
    assert blocked_for_self(FOR, requested_by=REQUESTER, requested_for=FOR, self_approval=False)
    assert not blocked_for_self(FOR, requested_by=REQUESTER, requested_for=FOR, self_approval=True)


def test_a_rejection_needs_a_reason_an_approval_a_comment_when_required() -> None:
    """REQ-SR-028 AC1, AC2."""
    assert decision_problems(Decision.REJECT, "  ", comments_required=False) == [
        ("comment", "reason_required")
    ]
    assert decision_problems(Decision.APPROVE, None, comments_required=False) == []
    assert decision_problems(Decision.APPROVE, None, comments_required=True) == [
        ("comment", "comment_required")
    ]
    assert decision_problems(Decision.REJECT, "Not in budget", comments_required=False) == []
    assert decision_problems(Decision.APPROVE, "x" * 4001, comments_required=False) == [
        ("comment", "value_too_long")
    ]
