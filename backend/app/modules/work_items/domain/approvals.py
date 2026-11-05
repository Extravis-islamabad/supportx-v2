"""The approval engine's rules (WP-030 s2; REQ-SR-021..028, -061, -063).

Pure rules on plain values. One approver model for every record type (REQ-SR-063): a stage
names people or "the manager of the person the request is for"; the engine resolves them to
active people, never the requester or the person it is for unless the item allows
self-approval (REQ-SR-027), and never to nobody (REQ-SR-023): the stage's backup, else the
tenant's approval administrators, with the reason kept on the approval.

At MVP a record has one stage and any one approver decides it (plan D4): the first approval
approves it, the first rejection rejects it, and the other approvers' entries are closed as no
longer needed. Multi-stage and "everyone must approve" stages come with `catalog` (REQ-SR-029).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

COMMENT_MAX = 4000


class ApprovalState(StrEnum):
    """One approver's entry (REQ-SR-024)."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"  # the requester withdrew the request (REQ-SR-061)
    NOT_NEEDED = "not_needed"  # another approver decided the stage first


OPEN_STATES = frozenset({ApprovalState.PENDING})


class ApproverOrigin(StrEnum):
    """Why this person (or group) holds the approval."""

    NAMED = "named"
    MANAGER = "manager"  # the requested-for person's manager (REQ-SR-022)
    BACKUP = "backup"  # the stage's backup approver (REQ-SR-023)
    ADMINISTRATORS = "administrators"  # anyone with work_items.approve_any (REQ-SR-023)


class ApprovalPurpose(StrEnum):
    """What an approval decides (WP-044b s4)."""

    RECORD = "record"  # the record's own approval (a request's item, a problem asked ad hoc)
    ACCEPT_WITHOUT_FIX = "accept_without_fix"  # a known error kept without a fix (REQ-PRB-050)


class RouteReason(StrEnum):
    """Why an approval went to the backup or the administrators (shown on the record)."""

    NO_MANAGER = "no_manager"
    APPROVER_INACTIVE = "approver_inactive"
    SELF_APPROVAL_BLOCKED = "self_approval_blocked"


class DecisionChannel(StrEnum):
    """Where a decision was made (REQ-SR-024 AC2)."""

    APP = "app"
    PORTAL = "portal"
    EMAIL_LINK = "email_link"


class Decision(StrEnum):
    """What an approver decides."""

    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True)
class ApproverSpec:
    """One approver as the item names it (kind is the catalog's `person` or manager kind)."""

    manager_of_requested_for: bool
    person_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Person:
    """What the engine needs to know of a candidate approver."""

    user_id: uuid.UUID
    active: bool


@dataclass(frozen=True)
class StageInput:
    """A stage as the item names it, and the people the request involves."""

    approvers: Sequence[ApproverSpec]
    backup_id: uuid.UUID | None
    self_approval: bool
    requested_by: uuid.UUID
    requested_for: uuid.UUID
    manager_id: uuid.UUID | None  # of the requested-for person, read at submission


@dataclass(frozen=True)
class Assignment:
    """One approval to open: a person, or None for the approval administrators."""

    approver_id: uuid.UUID | None
    origin: ApproverOrigin
    reason: RouteReason | None = None


def resolve(stage: StageInput, people: dict[uuid.UUID, Person]) -> list[Assignment]:
    """The approvals a stage opens: never empty, never a blocked person (REQ-SR-023, -027).

    `people` holds every candidate (named, manager, backup); one missing counts as inactive.
    """
    blocked = set() if stage.self_approval else {stage.requested_by, stage.requested_for}
    found: list[Assignment] = []
    reasons: list[RouteReason] = []
    seen: set[uuid.UUID] = set()
    for spec in stage.approvers:
        candidate = stage.manager_id if spec.manager_of_requested_for else spec.person_id
        origin = ApproverOrigin.MANAGER if spec.manager_of_requested_for else ApproverOrigin.NAMED
        if candidate is None:
            reasons.append(RouteReason.NO_MANAGER)
            continue
        person = people.get(candidate)
        if person is None or not person.active:
            reasons.append(RouteReason.APPROVER_INACTIVE)
            continue
        if candidate in blocked:
            reasons.append(RouteReason.SELF_APPROVAL_BLOCKED)
            continue
        if candidate not in seen:
            seen.add(candidate)
            found.append(Assignment(candidate, origin))
    if found:
        return found
    reason = reasons[0] if reasons else RouteReason.APPROVER_INACTIVE
    backup = people.get(stage.backup_id) if stage.backup_id is not None else None
    if backup is not None and backup.active and backup.user_id not in blocked:
        return [Assignment(backup.user_id, ApproverOrigin.BACKUP, reason)]
    return [Assignment(None, ApproverOrigin.ADMINISTRATORS, reason)]


def decision_problems(
    decision: Decision, comment: str | None, *, comments_required: bool
) -> list[tuple[str, str]]:
    """A rejection always needs a reason; an approval a comment when the item says so (-028)."""
    text = (comment or "").strip()
    if len(text) > COMMENT_MAX:
        return [("comment", "value_too_long")]
    if text:
        return []
    if decision is Decision.REJECT:
        return [("comment", "reason_required")]
    if comments_required:
        return [("comment", "comment_required")]
    return []


def blocked_for_self(
    actor: uuid.UUID, *, requested_by: uuid.UUID, requested_for: uuid.UUID, self_approval: bool
) -> bool:
    """Segregation of duties at decision time (REQ-SR-027 AC2), for the administrators' entry."""
    return not self_approval and actor in {requested_by, requested_for}


__all__ = [
    "COMMENT_MAX",
    "OPEN_STATES",
    "ApprovalState",
    "ApproverOrigin",
    "ApproverSpec",
    "Assignment",
    "Decision",
    "DecisionChannel",
    "Person",
    "RouteReason",
    "StageInput",
    "blocked_for_self",
    "decision_problems",
    "resolve",
]
