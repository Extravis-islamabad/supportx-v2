"""How a service request's approval stages follow each other (WP-047a S2a; REQ-SR-029, -030).

Pure: no I/O. The stages are the item's, snapshotted on the request at submission, so changing
the item never moves a request already in flight (in the spirit of REQ-SR-022 AC3).

- Stages run in order. Stages next to each other that share a `parallel_group` form one step
  and open together (REQ-SR-030); the step passes when every stage in it passes, and fails on
  the first that fails (the others' pending approvals are then withdrawn).
- A stage whose condition does not hold is skipped (REQ-SR-032): it passes at once, shown with
  its condition.
- Each stage's own rule decides it (any, all, majority: the level engine's `level_outcome`,
  with the tenant's tie rule, D-146).
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.modules.work_items.domain.approvals import (
    ApproverOrigin,
    Assignment,
    LevelOutcome,
    RouteReason,
)


@dataclass(frozen=True)
class StagePlan:
    """One snapshotted stage as progression needs it: its number and its parallel group."""

    number: int  # 1-based, as `work_item_approvals.stage`
    parallel_group: str | None = None


def steps(plans: Sequence[StagePlan]) -> list[list[int]]:
    """The stage numbers grouped into steps: neighbours sharing a parallel group run together."""
    found: list[list[int]] = []
    for plan in plans:
        last = found[-1] if found else None
        joins = (
            last is not None
            and plan.parallel_group is not None
            and plans[plan.number - 2].parallel_group == plan.parallel_group
        )
        if joins and last is not None:
            last.append(plan.number)
        else:
            found.append([plan.number])
    return found


def step_outcome(numbers: Sequence[int], outcomes: Mapping[int, LevelOutcome]) -> LevelOutcome:
    """A step's outcome: rejected on the first rejected stage, approved when all are approved.

    A stage not yet in `outcomes` is pending. A tied majority (with the tenant's chair) waits.
    """
    states = [outcomes.get(n, LevelOutcome.PENDING) for n in numbers]
    if LevelOutcome.REJECTED in states:
        return LevelOutcome.REJECTED
    if all(s is LevelOutcome.APPROVED for s in states):
        return LevelOutcome.APPROVED
    return LevelOutcome.PENDING


def next_step(plans: Sequence[StagePlan], outcomes: Mapping[int, LevelOutcome]) -> list[int] | None:
    """The stages to open next: the first step not yet approved, or None when all are done.

    The caller checks `request_outcome` first: a rejected step ends the request's approval.
    """
    for step in steps(plans):
        if step_outcome(step, outcomes) is not LevelOutcome.APPROVED:
            return [n for n in step if n not in outcomes]
    return None


def request_outcome(
    plans: Sequence[StagePlan], outcomes: Mapping[int, LevelOutcome]
) -> LevelOutcome:
    """The whole approval: rejected when any step is, approved when every step is."""
    results = [step_outcome(step, outcomes) for step in steps(plans)]
    if LevelOutcome.REJECTED in results:
        return LevelOutcome.REJECTED
    if all(r is LevelOutcome.APPROVED for r in results):
        return LevelOutcome.APPROVED
    return LevelOutcome.PENDING


# --- who holds a stage once its approvers are resolved -------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """One person a stage's approvers resolved to, and how (the origin shown on the record)."""

    user_id: uuid.UUID
    origin: ApproverOrigin


def ci_owner_targets(
    owners: Sequence[tuple[uuid.UUID | None, uuid.UUID | None]],
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Who a "CI owner" approver asks: (people, groups whose members are asked), in order.

    Named on purpose (lane B's #582 review): a CI's owner person, when it has one, is the
    accountable owner and approves alone; its owner group is asked only when no person is
    named. `managed_by` is never an owner (cmdb's port does not return it).
    """
    people = [person for person, _ in owners if person is not None]
    groups = [group for person, group in owners if person is None and group is not None]
    return list(dict.fromkeys(people)), list(dict.fromkeys(groups))


def assign(
    candidates: Sequence[Candidate],
    eligible: Mapping[uuid.UUID, bool],
    *,
    requester: uuid.UUID,
    backup_id: uuid.UUID | None,
) -> tuple[list[Assignment], bool]:
    """The stage's approvals, never empty, and whether the requester was taken out.

    - The requester never approves their own request (the coordinator's S2 condition 2), even
      when the item allows self-approval: they are left out and the caller audits it.
    - A person who is not active or may not sign in is left out (lane B's owner notes).
    - Nobody left: the stage's backup, else the approval administrators, with the reason
      recorded (condition 3): `self_approval_blocked` when only the requester matched,
      `approver_inactive` when only unusable people did, `no_approver` when nobody did.
    """
    found: list[Assignment] = []
    seen: set[uuid.UUID] = set()
    dropped_requester = inactive = False
    for c in candidates:
        if c.user_id == requester:
            dropped_requester = True
            continue
        if not eligible.get(c.user_id, False):
            inactive = True
            continue
        if c.user_id not in seen:
            seen.add(c.user_id)
            found.append(Assignment(c.user_id, c.origin))
    if found:
        return found, dropped_requester
    reason = (
        RouteReason.SELF_APPROVAL_BLOCKED
        if dropped_requester
        else RouteReason.APPROVER_INACTIVE
        if inactive
        else RouteReason.NO_APPROVER
    )
    if backup_id is not None and backup_id != requester and eligible.get(backup_id, False):
        return [Assignment(backup_id, ApproverOrigin.BACKUP, reason)], dropped_requester
    return [Assignment(None, ApproverOrigin.ADMINISTRATORS, reason)], dropped_requester
