"""A stage's open tasks hold the move out of it, named (REQ-CHG-094, REQ-REL-048 AC1).

Shared by the change and release guards (lane A's OK, WP-058b S3). The refusal carries how many
are open (`tasks`), the stage, and the first open task by position (its title and ID, never its
text), with `more` for the rest, so the screen can say "…open: Back up the config and 2 more".
Canceling is never held up.
"""

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_items.domain.parts import TaskStatus
from app.modules.work_items.domain.stages import Move
from app.modules.work_items.infra.models import WorkItem, WorkItemTask
from app.modules.work_items.service import stages as stage_service

STAGE_TASKS_OPEN = "stage_tasks_open"
CANCELED = "closure_canceled"  # changes' and releases' cancel status


def _open(record: WorkItem) -> tuple[ColumnElement[bool], ...]:
    return (
        WorkItemTask.work_item_id == record.id,
        WorkItemTask.stage == record.stage,
        WorkItemTask.status.not_in((TaskStatus.DONE.value, TaskStatus.CANCELED.value)),
        WorkItemTask.deleted_at.is_(None),
    )


async def refusal(
    session: AsyncSession, record: WorkItem, move: Move
) -> stage_service.Refusal | None:
    """The refusal for leaving a stage with open tasks, naming the first; None when none."""
    if move.target.code == CANCELED or record.stage is None:
        return None
    if move.landed.stage == record.stage:
        return None
    count = int(await session.scalar(select(func.count()).where(*_open(record))) or 0)
    if count == 0:
        return None
    first = (
        await session.execute(
            select(WorkItemTask.id, WorkItemTask.title)
            .where(*_open(record))
            .order_by(WorkItemTask.position, WorkItemTask.id)
            .limit(1)
        )
    ).one()
    return stage_service.Refusal(
        STAGE_TASKS_OPEN,
        {
            # `tasks`, not `count`: the 409 keeps `count` for how many refusals it has.
            "tasks": count,
            "stage": str(record.stage),
            "task": first.title,
            "task_id": str(first.id),
            "more": count - 1,
        },
    )
