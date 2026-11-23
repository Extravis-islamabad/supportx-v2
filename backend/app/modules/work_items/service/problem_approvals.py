"""Approvals asked ad hoc on a problem or an incident (the approval engine made type-generic).

WP-044b s4 (REQ-PRB-050) for problems; WP-046b S1 (REQ-INC-083) for incidents.

Incidents choose how their approvers decide (any one, all, a majority: REQ-INC-083); problems
keep "the first decision decides".

A technician who may edit the problem asks named people to approve, ad hoc. Each person holds
`problems.approve`, and the first decision decides (the engine's "any" rule, REQ-SR-025). The
problem's status never moves on a decision: it records the approval status. Accepting a known
error without a fix (`accept_without_fix`) needs a live known error. Once approved, it is
accepted and gets a review date 90 days ahead (Appendix A).

Approvers are told through the in-app inbox (`GET /problems/my-approvals`, the approval event).
E-mailed decision links stay with service requests (D-132) for now.
"""

import uuid
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict
from app.modules.identity_access import Subject, UserType, person_placement
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain.lifecycle import FINAL_CATEGORIES, StatusCategory
from app.modules.work_items.domain.service_requests import ApprovalStatus
from app.modules.work_items.domain.types import PROBLEM, WorkItemType
from app.modules.work_items.infra.models import WorkItem, WorkItemApproval
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.approval_stage import approval_event
from app.shared.history import Source

MAX_APPROVERS = 10


class Subjects(Protocol):
    """The policy service as this needs it: another person's compiled rights."""

    async def subject(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, session: AsyncSession | None = None
    ) -> Subject:
        """The person's compiled subject."""
        ...


async def _eligible(  # noqa: PLR0913 - who asks, whom, about which record
    session: AsyncSession,
    policy: Subjects,
    subject: Subject,
    person: uuid.UUID,
    record_id: uuid.UUID,
    *,
    wtype: WorkItemType = PROBLEM,
) -> bool:
    """An active person (never a service identity) whose <type>.approve reaches the record."""
    placed = await person_placement(session, person)
    if not placed.active or placed.user_type == UserType.SERVICE.value:
        return False
    other = await policy.subject(subject.tenant_id, person, session)
    return await items.may(session, other, wtype, "approve", record_id)


async def request(  # noqa: PLR0913, C901 - the record, the people, the purpose, the checks
    session: AsyncSession,
    subject: Subject,
    problem_id: uuid.UUID,
    approver_ids: Sequence[uuid.UUID],
    *,
    purpose: rules.ApprovalPurpose,
    expected_version: int,
    source: Source,
    policy: Subjects,
    wtype: WorkItemType = PROBLEM,
    rule: rules.LevelRule | None = None,
) -> WorkItem:
    """Ask these people to approve; the record's approval status becomes pending.

    `rule` (incidents) says how they decide; none means the first decision decides.
    """
    record = await items.record_for_action(session, subject, wtype, "edit", problem_id)
    people = list(dict.fromkeys(approver_ids))
    if not people:
        raise items.field_errors([("approver_ids", "required")])
    if len(people) > MAX_APPROVERS:
        raise items.field_errors([("approver_ids", "too_many_records")], max=MAX_APPROVERS)
    # Four eyes (lane B's review): whoever asks never approves their own request, and every
    # approver can actually decide, so the problem never waits on someone who cannot.
    if subject.user_id in people:
        raise items.field_errors([("approver_ids", "approver_is_requester")])
    for person in people:
        if not await _eligible(session, policy, subject, person, record.id, wtype=wtype):
            raise items.field_errors(
                [("approver_ids", "approver_not_eligible")],
                approver_ids={"user_id": str(person)},  # the form marks whom to remove
            )
    if StatusCategory(record.status_category) in FINAL_CATEGORIES:
        raise Conflict(code="record_closed", params={"display_id": record.display_id})
    if wtype is not PROBLEM and purpose is not rules.ApprovalPurpose.RECORD:
        raise items.field_errors([("purpose", "invalid_choice")])
    if wtype is PROBLEM and rule is not None:  # a problem's first decision decides
        raise items.field_errors([("rule", "invalid_choice")])
    if purpose is rules.ApprovalPurpose.ACCEPT_WITHOUT_FIX and (
        record.known_error_at is None or record.known_error_retired_at is not None
    ):
        raise Conflict(code="not_known_error", params={"display_id": record.display_id})
    if record.approval_status == ApprovalStatus.PENDING:
        raise Conflict(code="approval_pending", params={"display_id": record.display_id})
    stage = (
        int(
            await session.scalar(
                select(func.coalesce(func.max(WorkItemApproval.stage), 0)).where(
                    WorkItemApproval.work_item_id == record.id
                )
            )
            or 0
        )
        + 1
    )
    updated = await items.set_fields(
        session,
        record,
        {"approval_status": ApprovalStatus.PENDING.value},
        expected_version=expected_version,
        source=source,
    )
    for person in people:
        row = WorkItemApproval(
            tenant_id=record.tenant_id,
            work_item_id=record.id,
            stage=stage,
            approver_id=person,
            origin=rules.ApproverOrigin.NAMED.value,
            purpose=purpose.value,
            rule=rule.value if rule is not None else None,
        )
        session.add(row)
        await session.flush()
        await approval_event(session, updated, row, "opened")
    return updated
