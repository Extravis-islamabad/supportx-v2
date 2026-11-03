"""How a service request starts from its catalog item (WP-030 s1; REQ-SR-004, -005, -008, -021).

Pure rules on plain values (the item is the catalog module's; work_items gets what it decides
through that module's package): the first status, the priority and where it came from, and who
it is assigned to at creation.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum

from app.modules.work_items.domain.lifecycle import DefaultStatus, ServiceRequestStatus

ITEM_SOURCE = "catalog_item"  # history and the priority marker name the item (REQ-SR-005 AC1)


class OnBehalfScope(StrEnum):
    """Whom a requester may raise a record for (REQ-SR-011); their direct reports always count."""

    SAME_DEPARTMENT = "same_department"
    SAME_SITE = "same_site"
    ALL_REQUESTERS = "all_requesters"
    ALL_USERS = "all_users"


@dataclass(frozen=True)
class PersonFacts:
    """What the on-behalf rule looks at for one person."""

    user_id: uuid.UUID
    department_id: uuid.UUID | None
    site_id: uuid.UUID | None
    is_requester: bool
    manager_id: uuid.UUID | None
    active: bool = True
    can_sign_in: bool = True


def may_raise_for(scope: OnBehalfScope, submitter: PersonFacts, target: PersonFacts) -> bool:
    """Whether `submitter` may raise a record for `target` under the tenant's scope (AC1).

    Never for a deactivated person; "any requester" means people who are requesters and can
    sign in (no service identities, no contacts without sign-in; lane B review).
    """
    if target.user_id == submitter.user_id:
        return True
    if not target.active:
        return False
    in_scope = {
        OnBehalfScope.ALL_USERS: True,
        OnBehalfScope.ALL_REQUESTERS: target.is_requester and target.can_sign_in,
        OnBehalfScope.SAME_SITE: submitter.site_id is not None
        and target.site_id == submitter.site_id,
        OnBehalfScope.SAME_DEPARTMENT: submitter.department_id is not None
        and target.department_id == submitter.department_id,
    }
    return target.manager_id == submitter.user_id or in_scope[scope]  # or their own report


class ApprovalStatus(StrEnum):
    """A service request's approval (REQ-SR-003)."""

    NOT_NEEDED = "not_needed"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


@dataclass(frozen=True)
class ItemDecides:
    """What the item says about a new request."""

    needs_approval: bool
    default_priority: str | None
    group_id: uuid.UUID | None
    technician_id: uuid.UUID | None
    technician_after_approval: bool


@dataclass(frozen=True)
class Start:
    """The new request's first values."""

    status: str
    priority: str
    priority_from_item: bool  # False: the tenant default (marked as defaulted, REQ-INC-011)
    group_id: uuid.UUID | None
    technician_id: uuid.UUID | None


def start(item: ItemDecides, *, tenant_default_priority: str) -> Start:
    """The first status, priority and assignment of a request from `item`.

    - Waiting for approval when the item needs one (REQ-SR-021); then the technician waits too if
      the item says "technician after approval" (REQ-SR-008 AC2); the group is set at once.
    - The item's default priority, else the tenant default: never blank (REQ-SR-005).
    - Without an approval, a set technician makes it "assigned" as for incidents (REQ-INC-050).
    """
    technician = item.technician_id
    if item.needs_approval and item.technician_after_approval:
        technician = None
    if item.needs_approval:
        status = ServiceRequestStatus.AWAITING_APPROVAL.value
    elif technician is not None:
        status = DefaultStatus.ASSIGNED.value
    else:
        status = DefaultStatus.NEW.value
    priority = item.default_priority or tenant_default_priority
    return Start(
        status=status,
        priority=priority,
        priority_from_item=item.default_priority is not None,
        group_id=item.group_id,
        technician_id=technician,
    )


def after_approval(item: ItemDecides, *, current_technician: uuid.UUID | None) -> uuid.UUID | None:
    """The technician to set once approved: the item's, if it waited for the approval."""
    if current_technician is None and item.technician_after_approval:
        return item.technician_id
    return current_technician


__all__ = [
    "ITEM_SOURCE",
    "ApprovalStatus",
    "ItemDecides",
    "OnBehalfScope",
    "PersonFacts",
    "Start",
    "after_approval",
    "may_raise_for",
    "start",
]
