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
from collections.abc import Iterable, Mapping, Sequence
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
    WORKFLOW = "workflow"  # a workflow's approval node opened it (WP-048b S2, REQ-WF-014)


class RouteReason(StrEnum):
    """Why an approval went to the backup or the administrators (shown on the record)."""

    NO_MANAGER = "no_manager"
    APPROVER_INACTIVE = "approver_inactive"
    SELF_APPROVAL_BLOCKED = "self_approval_blocked"
    # WP-058a s5 (staged types; lane B's review): never a stage stuck silently.
    NO_HOLDER = "no_holder"  # a role named as approver has nobody holding it


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


# --- levels with a rule (WP-058a s5; REQ-REL-031; staged types) ---------------------------------


class LevelRule(StrEnum):
    """How a level's approvers decide it."""

    ANY = "any"  # the first approval approves; a rejection rejects
    ALL = "all"  # everyone must approve; any rejection rejects
    MAJORITY = "majority"  # more than half must approve


class LevelOutcome(StrEnum):
    """Where a level stands."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIED = "tied"  # an exact majority split that a chair decides (D-146); only with a chair


def level_outcome(
    rule: LevelRule,
    states: Iterable[ApprovalState],
    *,
    chair: bool = False,
    chair_vote: ApprovalState | None = None,
) -> LevelOutcome:
    """The level's outcome from its approvers' states (withdrawn and not-needed do not count).

    Majority: more than half of the level's approvers must approve. Without a chair the level is
    rejected as soon as a majority can no longer be reached, so an exact split (2 of 4 each way)
    rejects: the tie case (the coordinator's condition, D-146). With the tenant's chair (D-146),
    a level that can still end in an exact split waits for it; the split is TIED until the
    chair's `chair_vote` decides it.
    """
    counted = [
        s
        for s in states
        if s in {ApprovalState.PENDING, ApprovalState.APPROVED, ApprovalState.REJECTED}
    ]
    if not counted:
        return LevelOutcome.PENDING
    approved = sum(s == ApprovalState.APPROVED for s in counted)
    rejected = sum(s == ApprovalState.REJECTED for s in counted)
    if rule == LevelRule.MAJORITY and chair:
        return _majority_with_chair(approved, rejected, len(counted), chair_vote)
    decide = {LevelRule.ANY: _any, LevelRule.ALL: _all, LevelRule.MAJORITY: _majority}[rule]
    return decide(approved, rejected, len(counted))


def _any(approved: int, rejected: int, total: int) -> LevelOutcome:
    del total
    if approved:
        return LevelOutcome.APPROVED
    return LevelOutcome.REJECTED if rejected else LevelOutcome.PENDING


def _all(approved: int, rejected: int, total: int) -> LevelOutcome:
    if rejected:
        return LevelOutcome.REJECTED
    return LevelOutcome.APPROVED if approved == total else LevelOutcome.PENDING


def _majority(approved: int, rejected: int, total: int) -> LevelOutcome:
    needed = total // 2 + 1
    if approved >= needed:
        return LevelOutcome.APPROVED
    if total - rejected < needed:  # the rest approving can no longer make a majority
        return LevelOutcome.REJECTED
    return LevelOutcome.PENDING


def _majority_with_chair(
    approved: int, rejected: int, total: int, vote: ApprovalState | None
) -> LevelOutcome:
    needed = total // 2 + 1
    if approved >= needed:
        return LevelOutcome.APPROVED
    split = total % 2 == 0 and approved == rejected == total // 2
    if split:
        if vote == ApprovalState.APPROVED:
            return LevelOutcome.APPROVED
        if vote == ApprovalState.REJECTED:
            return LevelOutcome.REJECTED
        return LevelOutcome.TIED
    tie_reachable = total % 2 == 0 and total - rejected >= total // 2
    if total - rejected < needed and not tie_reachable:
        return LevelOutcome.REJECTED
    return LevelOutcome.PENDING


@dataclass(frozen=True)
class LevelApprovers:
    """Who approves one level: people, groups (each member) and record roles (the holders)."""

    rule: LevelRule
    user_ids: tuple[uuid.UUID, ...] = ()
    group_ids: tuple[uuid.UUID, ...] = ()
    roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class StageApprovals:
    """A stage's approvals: raised by one status, ending in its approved or rejected status."""

    raised_by: str
    approved: str
    rejected: str
    levels: tuple[LevelApprovers, ...]
    self_approval: bool = False  # segregation of duties: the requester may not approve (AC4)


MAX_LEVELS = 5


def parse_stage_approvals(  # noqa: C901, PLR0912 - one check per part of the settings, flat
    raw: object, *, stage_statuses: Mapping[str, bool], roles: Iterable[str]
) -> tuple[StageApprovals | None, list[tuple[str, str]]]:
    """Settings from JSON, plus (field, code) problems.

    Checked against the stage's statuses (code -> system-only) and the type's roles. The outcome
    statuses must be system-only, so only the approvals set them (ADR-041 §2).
    """
    if raw is None:
        return None, []
    if not isinstance(raw, Mapping):
        return None, [("approvals", "invalid_value")]
    problems: list[tuple[str, str]] = []
    known_roles = set(roles)
    raised_by, approved, rejected = (raw.get(k) for k in ("raised_by", "approved", "rejected"))
    if raised_by not in stage_statuses or stage_statuses.get(str(raised_by)):
        problems.append(("approvals.raised_by", "invalid_choice"))
    for name, status in (("approved", approved), ("rejected", rejected)):
        if status not in stage_statuses or not stage_statuses[str(status)]:
            problems.append((f"approvals.{name}", "invalid_choice"))
    raw_levels = raw.get("levels")
    if not isinstance(raw_levels, list) or not raw_levels:
        problems.append(("approvals.levels", "required"))
        raw_levels = []
    if len(raw_levels) > MAX_LEVELS:
        problems.append(("approvals.levels", "too_many_items"))
    levels: list[LevelApprovers] = []
    for index, level in enumerate(raw_levels):
        where = f"approvals.levels.{index}"
        if not isinstance(level, Mapping):
            problems.append((where, "invalid_value"))
            continue
        try:
            rule = LevelRule(level.get("rule", LevelRule.ANY))
        except ValueError:
            problems.append((f"{where}.rule", "invalid_choice"))
            continue
        users: list[uuid.UUID] = []
        groups: list[uuid.UUID] = []
        named_roles: list[str] = []
        for approver in level.get("approvers") or []:
            if not isinstance(approver, Mapping) or len(approver) != 1:
                problems.append((f"{where}.approvers", "invalid_value"))
                continue
            ((key, value),) = approver.items()
            if key == "role" and str(value) in known_roles:
                named_roles.append(str(value))
            elif key in {"user_id", "group_id"} and _is_uuid(value):
                (users if key == "user_id" else groups).append(uuid.UUID(str(value)))
            else:
                problems.append((f"{where}.approvers", "invalid_value"))
        if not (users or groups or named_roles):
            problems.append((f"{where}.approvers", "required"))
        levels.append(LevelApprovers(rule, tuple(users), tuple(groups), tuple(named_roles)))
    if problems:
        return None, problems
    return (
        StageApprovals(
            str(raised_by),
            str(approved),
            str(rejected),
            tuple(levels),
            bool(raw.get("self_approval", False)),
        ),
        [],
    )


def _is_uuid(value: object) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


def stage_approvals_to_json(settings: StageApprovals) -> dict[str, object]:
    """The stored form."""
    return {
        "raised_by": settings.raised_by,
        "approved": settings.approved,
        "rejected": settings.rejected,
        "self_approval": settings.self_approval,
        "levels": [
            {
                "rule": level.rule.value,
                "approvers": [{"user_id": str(u)} for u in level.user_ids]
                + [{"group_id": str(g)} for g in level.group_ids]
                + [{"role": r} for r in level.roles],
            }
            for level in settings.levels
        ],
    }
