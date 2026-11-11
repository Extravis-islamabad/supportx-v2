"""The emergency CAB's way through a freeze (D-156, Haider 2026-11-11; lane B blocks).

An emergency change whose window is in a blocking freeze is saved, never refused
(change_conflicts.guard), and waits before implementation (change_guard). Its emergency CAB lets
it through: approving it while it is in a freeze needs a reason, and when the CAB stage is
approved, the change is stamped as passed (who decided last, when), audited and shown in its
history. The change manager's freeze override stays the other way, unchanged.

Only changes on the emergency path, only at their CAB stage; every other approval is untouched.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import WORKER as AUDIT_WORKER
from app.modules.audit import AuditActorType
from app.modules.audit import record as record_audit
from app.modules.work_items.domain import changes as rules
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemApproval,
    WorkItemChangeDetails,
)
from app.modules.work_items.service import catalogue, change_conflicts
from app.modules.work_items.service.followers import RECORD_TYPE
from app.shared.history import Change, Source, record_changes

CAB_STAGE = "cab_review"
AUDIT_ACTION = "change.freeze_passed_by_cab"


def _at_its_cab(record: WorkItem, row: WorkItemApproval) -> bool:
    return (
        record.type == "change"
        and record.stage_path == rules.EMERGENCY_PATH
        and row.record_stage == CAB_STAGE
    )


async def in_freeze(session: AsyncSession, record: WorkItem) -> bool:
    """Whether a blocking freeze no override covers holds the change now."""
    found, _ = await change_conflicts.conflicts(session, record)
    passed = await change_conflicts.passed_windows(session, record.id)
    return bool(change_conflicts.frozen_still(found, passed))


async def reason_needed(
    session: AsyncSession, record: WorkItem, row: WorkItemApproval, *, approving: bool
) -> bool:
    """An emergency CAB member approving a change in a freeze must say why (D-156)."""
    return approving and _at_its_cab(record, row) and await in_freeze(session, record)


async def after_cab_vote(
    session: AsyncSession,
    record: WorkItem,
    row: WorkItemApproval,
    *,
    decided_by: uuid.UUID,
    source: Source,
) -> bool:
    """Stamp the change as passed by its CAB once the CAB stage is approved, if in a freeze.

    A later approval (after a re-approval) stamps it again: the latest decision counts.

    Returns whether it stamped (so the caller's history line can say so). Audited as
    `change.freeze_passed_by_cab`, naming the approval; the reason is the approval's comment.
    """
    # The CAB stage approved: the change is past it (its completing status moves it on).
    if not _at_its_cab(record, row) or record.stage == CAB_STAGE:
        return False
    details = await session.get(WorkItemChangeDetails, (catalogue.tenant_of(session), record.id))
    if details is None:
        return False
    if not await in_freeze(session, record):
        return False
    details.freeze_cab_passed_at = datetime.now(UTC)
    details.freeze_cab_passed_by = decided_by
    await session.flush()
    await record_audit(
        session,
        action_code=AUDIT_ACTION,
        facts=AUDIT_WORKER,
        actor=(AuditActorType.PERSON, decided_by),
        object_type="work_item",
        object_id=str(record.id),
        details={"approval_id": str(row.id), "stage": CAB_STAGE},
        reason=row.comment,
    )
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="updated",
        changes=[Change("freeze_passed_by_cab", None, new=True)],
        source=source,
        reason=row.comment,
    )
    return True
