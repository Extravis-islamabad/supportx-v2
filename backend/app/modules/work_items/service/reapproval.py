"""Re-approval of an approved change (WP-045b S4; REQ-CHG-053).

When a stage's approvals complete as approved, the change's watched values are kept
(`take`). `changes_since` lists, per approved stage, what changed since, field by field (AC3);
`after_save` runs after a save of the window, the risk or a plan and reopens the approval of
every stage whose policy says restart (AC1, AC2). Notified changes are listed; the notice to the
board's members comes with the change notifications (WP-056).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import Subject
from app.modules.work_items.domain import reapproval as rules
from app.modules.work_items.domain.change_risk import RiskLevel
from app.modules.work_items.domain.changes import IMPLEMENTATION
from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.infra.models import (
    ChangeApprovalSnapshot,
    WorkItem,
    WorkItemChangeDetails,
    WorkItemPlanSection,
    WorkItemStageSchedule,
)
from app.modules.work_items.service import catalogue
from app.modules.work_items.service import work_items as items
from app.shared.ids import new_id

CHANGE = TYPES[WorkItemTypeCode.CHANGE]


async def snapshot_now(session: AsyncSession, record: WorkItem) -> rules.Snapshot:
    """The change's watched values as they are now."""
    window = await session.scalar(
        select(WorkItemStageSchedule).where(
            WorkItemStageSchedule.work_item_id == record.id,
            WorkItemStageSchedule.stage == IMPLEMENTATION,
        )
    )
    details = await session.scalar(
        select(WorkItemChangeDetails).where(WorkItemChangeDetails.work_item_id == record.id)
    )
    risk = None if details is None else (details.risk_chosen or details.risk)
    plans = {
        s.section: s.version
        for s in await session.scalars(
            select(WorkItemPlanSection).where(WorkItemPlanSection.work_item_id == record.id)
        )
    }
    return rules.Snapshot(
        window.scheduled_start if window else None,
        window.scheduled_end if window else None,
        RiskLevel(risk) if risk else None,
        plans,
    )


async def take(session: AsyncSession, record: WorkItem, stage: str) -> None:
    """Keep the watched values now: the stage was just approved."""
    if record.type != WorkItemTypeCode.CHANGE:
        return
    now = await snapshot_now(session, record)
    session.add(
        ChangeApprovalSnapshot(
            id=new_id(),
            tenant_id=record.tenant_id,
            work_item_id=record.id,
            record_stage=stage,
            snapshot=now.to_json(),
        )
    )
    await session.flush()


async def _latest(session: AsyncSession, record_id: uuid.UUID) -> dict[str, rules.Snapshot]:
    """Each approved stage's latest snapshot."""
    rows = await session.scalars(
        select(ChangeApprovalSnapshot)
        .where(ChangeApprovalSnapshot.work_item_id == record_id)
        .order_by(ChangeApprovalSnapshot.created_at, ChangeApprovalSnapshot.id)
    )
    return {r.record_stage: rules.Snapshot.from_json(r.snapshot) for r in rows}


@dataclass(frozen=True)
class StageChanges:
    """What changed since one stage was approved."""

    stage: str
    changes: tuple[rules.FieldChange, ...]


async def _compare(session: AsyncSession, record: WorkItem) -> list[StageChanges]:
    approved = await _latest(session, record.id)
    if not approved:
        return []
    policy = rules.policy_from((await catalogue.load(session, CHANGE)).reapproval)
    now = await snapshot_now(session, record)
    return [
        StageChanges(stage, tuple(rules.compare(before, now, policy)))
        for stage, before in approved.items()
    ]


async def changes_since(
    session: AsyncSession, subject: Subject, record_id: uuid.UUID
) -> list[StageChanges]:
    """Per approved stage, what changed since its approval (REQ-CHG-053 AC3)."""
    record = await items.visible_record(session, subject, CHANGE, record_id)
    return [s for s in await _compare(session, record) if s.changes]


async def to_restart(session: AsyncSession, record: WorkItem) -> list[StageChanges]:
    """The approved stages whose approval a save's changes restart (AC1, AC2)."""
    return [s for s in await _compare(session, record) if rules.restarts(list(s.changes))]
