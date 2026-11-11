"""A change's rules around a move (WP-045a D4; ADR-041 §5): approvals and the outcome.

One guard per type: the stage approvals' guard (Appendix A's acceptance, plan and CAB
approvals, superseded on going back) plus the change's own refusal, that implementation is
completed only with its outcome, and the status that says the same (REQ-CHG-032 AC1).
"""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_items.domain import changes as rules
from app.modules.work_items.domain.lifecycle import StatusCategory
from app.modules.work_items.domain.parts import LinkKind, TaskStatus
from app.modules.work_items.domain.stages import Move
from app.modules.work_items.domain.types import WorkItemType, WorkItemTypeCode
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemChangeDetails,
    WorkItemLink,
    WorkItemStageSchedule,
    WorkItemTask,
)
from app.modules.work_items.service import catalogue
from app.modules.work_items.service import stages as stage_service
from app.modules.work_items.service.stage_approvals import StagedApprovalGuard


class ChangeGuard(StagedApprovalGuard):
    """The approvals guard, and the implementation outcome a completing move needs."""

    async def check(
        self, session: AsyncSession, record: WorkItem, move: Move
    ) -> list[stage_service.Refusal]:
        """The approvals' refusals, then the outcome's (REQ-CHG-032 AC1)."""
        # The parent's sub-release check runs too: a no-op for changes (no release children).
        refusals = await super().check(session, record, move)
        refusals = [*refusals, *await _stage_work_refusals(session, record, move)]
        # Closing, not canceling: a change may always be canceled.
        if move.target.code == rules.CLOSED_STATUS and record.stage != rules.REVIEW:
            details = await session.get(
                WorkItemChangeDetails, (catalogue.tenant_of(session), record.id)
            )
            if details is not None and details.pir_required:  # D-144: after an override
                refusals = [*refusals, stage_service.Refusal("pir_required", {})]
        if move.target.code not in rules.OUTCOME_OF_STATUS:
            return refusals
        row = await session.get(
            WorkItemStageSchedule,
            (catalogue.tenant_of(session), record.id, rules.IMPLEMENTATION),
        )
        # No schedule row yet is no outcome yet: refused as outcome_required, never passed.
        refused = rules.outcome_refusal(move.target.code, row.outcome if row else None)
        if refused is None:
            return refusals
        code, params = refused
        return [*refusals, stage_service.Refusal(code, params)]


CANCELED = "closure_canceled"


async def _stage_work_refusals(
    session: AsyncSession, record: WorkItem, move: Move
) -> list[stage_service.Refusal]:
    """A stage's own tasks done before it is left; children done before closing.

    REQ-CHG-094: the stage's open tasks hold the move out of it. REQ-CHG-096: a change is
    closed only when its child changes and releases are. Canceling is never held up.
    """
    if move.target.code == CANCELED:
        return []
    found: list[stage_service.Refusal] = []
    leaving = move.landed.stage != record.stage
    if leaving and record.stage is not None:
        open_tasks = await session.scalar(
            select(func.count()).where(
                WorkItemTask.work_item_id == record.id,
                WorkItemTask.stage == record.stage,
                WorkItemTask.status.not_in((TaskStatus.DONE.value, TaskStatus.CANCELED.value)),
                WorkItemTask.deleted_at.is_(None),
            )
        )
        if open_tasks:
            found.append(
                stage_service.Refusal(
                    "stage_tasks_open", {"count": int(open_tasks), "stage": str(record.stage)}
                )
            )
    if move.landed.code == rules.CLOSED_STATUS:
        children = await session.scalar(
            select(func.count())
            .select_from(WorkItemLink)
            .join(WorkItem, WorkItem.id == WorkItemLink.source_id)
            .where(
                WorkItemLink.target_id == record.id,
                WorkItemLink.kind == LinkKind.PART_OF_CHANGE.value,
                WorkItemLink.deleted_at.is_(None),
                WorkItem.deleted_at.is_(None),
                WorkItem.status_category.not_in(
                    (StatusCategory.CLOSED.value, StatusCategory.CANCELED.value)
                ),
            )
        )
        if children:
            found.append(stage_service.Refusal("children_open", {"count": int(children)}))
    return found


def register(types: Sequence[WorkItemType]) -> None:
    """Register the change's guard (releases register the approvals guard of their own)."""
    for wtype in types:
        if wtype.code is WorkItemTypeCode.CHANGE:
            stage_service.register_guard(wtype.code, ChangeGuard(wtype))
