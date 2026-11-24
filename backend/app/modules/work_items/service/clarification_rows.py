"""Open clarifications on request approvals (WP-047a S3a; REQ-SR-037): read and end them.

Kept apart from `clarifications` (asking, answering) so the approvals service can end a row's
open question when it closes without importing what imports it.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_items.domain.clarifications import ClarificationEnd
from app.modules.work_items.events import ClarificationChange, WorkItemApprovalClarification
from app.modules.work_items.infra.models import ApprovalClarification, WorkItem, WorkItemApproval
from app.shared.events import record_event


async def for_record(session: AsyncSession, record_id: uuid.UUID) -> list[ApprovalClarification]:
    """Every clarification of a record, newest last."""
    return list(
        await session.scalars(
            select(ApprovalClarification)
            .where(
                ApprovalClarification.work_item_id == record_id,
                ApprovalClarification.deleted_at.is_(None),
            )
            .order_by(ApprovalClarification.asked_at, ApprovalClarification.id)
        )
    )


async def open_for(
    session: AsyncSession, approval_ids: Sequence[uuid.UUID]
) -> list[ApprovalClarification]:
    """The open questions on these approvals (at most one each), locked for the change."""
    if not approval_ids:
        return []
    return list(
        await session.scalars(
            select(ApprovalClarification)
            .where(
                ApprovalClarification.approval_id.in_(approval_ids),
                ApprovalClarification.ended_at.is_(None),
                ApprovalClarification.deleted_at.is_(None),
            )
            .with_for_update()
        )
    )


async def event(
    session: AsyncSession,
    record: WorkItem,
    row: ApprovalClarification,
    change: ClarificationChange,
) -> None:
    """The clarification's event, in the same transaction (outbox): IDs and codes only."""
    await record_event(
        session,
        WorkItemApprovalClarification(
            work_item_id=record.id,
            type=record.type,
            approval_id=row.approval_id,
            approver_id=row.asked_by,
            clarification_id=row.id,
            addressee=row.addressee,
            change=change,
        ),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )


async def end(
    session: AsyncSession,
    record: WorkItem,
    row: ApprovalClarification,
    how: ClarificationEnd,
    *,
    answer_entry_id: uuid.UUID | None = None,
) -> None:
    """End one open question; an answer gives the approval its paused time back (AC3)."""
    now = datetime.now(UTC)
    row.ended_at = now
    row.ended_how = how.value
    row.answer_entry_id = answer_entry_id
    row.version += 1
    approval = await session.get(WorkItemApproval, row.approval_id, with_for_update=True)
    if approval is not None:
        approval.paused_seconds += max(0, int((now - row.asked_at).total_seconds()))
        approval.version += 1
    await session.flush()
    await event(session, record, row, "answered" if how is ClarificationEnd.ANSWERED else "ended")


async def end_open(
    session: AsyncSession,
    record: WorkItem,
    approval_ids: Sequence[uuid.UUID],
    how: ClarificationEnd,
) -> int:
    """End every open question on these approvals (decided, or the approval closed)."""
    found = await open_for(session, approval_ids)
    for row in found:
        await end(session, record, row, how)
    return len(found)
