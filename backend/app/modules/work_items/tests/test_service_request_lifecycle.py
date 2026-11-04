"""The service request life cycle (WP-030, REQ-SR-004; no I/O)."""

import pytest

from app.modules.work_items.domain.lifecycle import (
    DEFAULT_STATUSES,
    SERVICE_REQUEST_STATUSES,
    SYSTEM_ACTIONS,
    USER_ACTIONS,
    Lifecycle,
    LifecycleError,
    ServiceRequestStatus,
    StatusCategory,
    StatusDef,
    TransitionDef,
    WorkItemAction,
    service_request_lifecycle,
)

A = WorkItemAction
SR = ServiceRequestStatus


def test_it_builds_and_adds_approval_fulfilled_and_rejected() -> None:
    life = service_request_lifecycle()
    codes = {s.code for s in SERVICE_REQUEST_STATUSES}
    assert {"awaiting_approval", "fulfilled", "rejected"} <= codes
    assert "resolved" not in codes  # "fulfilled" never shows as "resolved" (AC4)
    assert life.category(SR.AWAITING_APPROVAL) is StatusCategory.PAUSED
    assert life.category(SR.REJECTED) is StatusCategory.CLOSED
    assert life.category(SR.FULFILLED) is StatusCategory.RESOLVED


def test_approval_opens_it_and_rejection_ends_it() -> None:
    life = service_request_lifecycle()
    assert (
        life.target(SR.AWAITING_APPROVAL, A.APPROVE, before_cancel=None) == "new"
    )  # then `assign` if set (AC2)
    assert life.allows("new", A.ASSIGN)
    assert life.target(SR.AWAITING_APPROVAL, A.REJECT, before_cancel=None) == SR.REJECTED
    assert life.allows(SR.AWAITING_APPROVAL, A.CANCEL)  # withdraw (REQ-SR-061)
    # A rejected request cannot be reopened (REQ-SR-060); a fulfilled one closes or reopens.
    assert not any(life.allows(SR.REJECTED, action) for action in A)
    assert life.target(SR.FULFILLED, A.CLOSE, before_cancel=None) == "closed"
    assert life.target("in_progress", A.RESOLVE, before_cancel=None) == SR.FULFILLED


def test_nobody_chooses_awaiting_approval_or_rejected() -> None:
    """AC3: approve and reject are system actions; no user action leads into a system status."""
    assert {A.APPROVE, A.REJECT} <= SYSTEM_ACTIONS
    assert A.APPROVE not in USER_ACTIONS
    assert A.REJECT not in USER_ACTIONS
    life = service_request_lifecycle()
    system = {s.code for s in SERVICE_REQUEST_STATUSES if s.system}
    for status in (s.code for s in SERVICE_REQUEST_STATUSES):
        for action in USER_ACTIONS:
            if action is A.UNDO_CANCEL:  # back to the status before canceling, never new
                continue
            if life.allows(status, action):
                assert life.target(status, action, before_cancel=None) not in system, (
                    status,
                    action,
                )


def test_a_user_action_into_a_system_status_is_still_refused() -> None:
    statuses = (*DEFAULT_STATUSES, StatusDef("held", StatusCategory.PAUSED, "#000000", system=True))
    with pytest.raises(LifecycleError, match="system only"):
        Lifecycle.build(statuses, (TransitionDef("new", A.START_WORK, "held"),))
