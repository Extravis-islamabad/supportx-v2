"""Approvals on a problem (WP-044b s4; REQ-PRB-050, the approval engine made type-generic).

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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict
from app.modules.identity_access import Subject
from app.modules.work_items.domain import approvals as rules
from app.modules.work_items.domain.lifecycle import FINAL_CATEGORIES, StatusCategory
from app.modules.work_items.domain.service_requests import ApprovalStatus
from app.modules.work_items.domain.types import PROBLEM
from app.modules.work_items.infra.models import WorkItem, WorkItemApproval
from app.modules.work_items.service import work_items as items
from app.modules.work_items.service.approval_stage import approval_event
from app.shared.history import Source

MAX_APPROVERS = 10


async def request(  # noqa: PLR0913 - the problem, the people, the purpose and the source
    session: AsyncSession,
    subject: Subject,
    problem_id: uuid.UUID,
    approver_ids: Sequence[uuid.UUID],
    *,
    purpose: rules.ApprovalPurpose,
    expected_version: int,
    source: Source,
) -> WorkItem:
    """Ask these people to approve; the record's approval status becomes pending."""
    record = await items.record_for_action(session, subject, PROBLEM, "edit", problem_id)
    people = list(dict.fromkeys(approver_ids))
    if not people:
        raise items.field_errors([("approver_ids", "required")])
    if len(people) > MAX_APPROVERS:
        raise items.field_errors([("approver_ids", "too_many_records")], max=MAX_APPROVERS)
    if StatusCategory(record.status_category) in FINAL_CATEGORIES:
        raise Conflict(code="record_closed", params={"display_id": record.display_id})
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
        )
        session.add(row)
        await session.flush()
        await approval_event(session, updated, row, "opened")
    return updated
