"""Fulfilment from the catalog item's plan (WP-030 s3, plan D8; REQ-SR-046, -058, -060).

On approval, or at submission when no approval is needed, the item's plan becomes the
request's tasks, in order (history names each one). When the last required plan task is done
and the item fulfils automatically, the request moves to "fulfilled" by itself (history:
automatic, rule `fulfilment`). Open fulfilment tasks then block closing through WP-020f's open
work check, as any task does. A rejection creates none (REQ-SR-060).
"""

import html
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, PermissionDenied, ValidationFailed
from app.modules import service_catalog
from app.modules.organization import users_in_groups
from app.modules.work_items.domain.lifecycle import DefaultStatus, StatusCategory, WorkItemAction
from app.modules.work_items.domain.parts import TaskPriority, TaskStatus
from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.events import ServiceRequestReadyToFulfil
from app.modules.work_items.infra.models import WorkItem, WorkItemTask
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service import closing, parts
from app.modules.work_items.service import work_items as items
from app.shared.events import record_event
from app.shared.history import Change, Source

FULFILMENT_RULE = "fulfilment"  # history's automatic move: the last required task was done
FIRST_TASK_RULE = "first_task"  # history's automatic move: the first task ticked (D-154c)
# Where ticking the first task starts the work from (D-154c): not yet being worked.
NOT_STARTED = frozenset({DefaultStatus.NEW.value, DefaultStatus.ASSIGNED.value})
TITLE_MAX = 200
RESOLUTION_MAX = 4000


def _title(names: dict[str, str] | object) -> str:
    """The step's title in English, else its first language (titles are kept per record)."""
    found = dict(names) if isinstance(names, dict) else {}
    text = found.get("en") or next(iter(found.values()), "")
    return str(text).strip()[:TITLE_MAX] or "-"


def _done_summary(planned: list[WorkItemTask]) -> str:
    """The resolution of an automatic fulfilment: the required tasks that were done, by name.

    Closing rules may require a resolution; this one is the record's own words, so it needs no
    translation and says exactly what was done.
    """
    # Resolution is rich text shown as HTML: the titles are escaped, never markup.
    return "<p>" + html.escape("; ".join(t.title for t in planned)[:RESOLUTION_MAX]) + "</p>"


async def start_plan(
    session: AsyncSession,
    record: WorkItem,
    item: service_catalog.RequestItem | None,
    *,
    source: Source,
) -> list[WorkItemTask]:
    """The item's plan as the request's tasks, after any it already has (REQ-SR-046 AC1)."""
    if item is None or not item.plan:
        return []
    existing = await parts.tasks_of(session, record.id)
    position = (existing[-1].position + 1) if existing else 0
    made: list[WorkItemTask] = []
    for step in item.plan:
        task = await parts.TaskRepository(session).add(
            WorkItemTask(
                work_item_id=record.id,
                title=_title(dict(step.title)),
                owner_id=step.owner_id,
                group_id=step.group_id,
                status=TaskStatus.OPEN.value,
                priority=TaskPriority.NORMAL.value,
                position=position,
                from_plan=True,
                required=step.required,
                internal=step.internal,
            )
        )
        position += 1
        await parts.recorded(
            session,
            record,
            "task",
            task.id,
            "child_added",
            [Change("task", None, task.title)],
            source,
        )
        made.append(task)
    return made


async def _ticked_by_its_people(
    session: AsyncSession, record: WorkItem, ticked_by: uuid.UUID
) -> bool:
    """The request's own technician, or someone of its group (D-154c)."""
    if ticked_by == record.technician_id:
        return True
    if record.group_id is None:
        return False
    members = await session.scalars(users_in_groups(frozenset({record.group_id})))
    return ticked_by in set(members)


async def _start_on_first_task(
    session: AsyncSession, record: WorkItem, ticked_by: uuid.UUID, *, source: Source
) -> WorkItem:
    """A New or Assigned request whose task its own people ticked moves to In progress (D-154c).

    The tenant may turn it off (`first_task_starts_work`). Nobody is assigned by it (D-154d):
    the move is the system's, recorded as automatic with rule `first_task`.
    """
    if record.status not in NOT_STARTED:
        return record
    wtype = TYPES[WorkItemTypeCode.SERVICE_REQUEST]
    cat = await config.load(session, wtype)
    lifecycle = cat.lifecycle_of(record.lifecycle)
    if not cat.first_task_starts_work or not lifecycle.allows(
        record.status, WorkItemAction.START_WORK
    ):
        return record
    if not await _ticked_by_its_people(session, record, ticked_by):
        return record
    try:
        async with session.begin_nested():  # a refused move leaves the task's own save
            return await items.system_move(
                session,
                wtype,
                cat,
                record,
                WorkItemAction.START_WORK,
                source=source,
                rule=FIRST_TASK_RULE,
                by_requester=False,
            )
    except (ValidationFailed, Conflict, PermissionDenied):
        return record


async def _tell_ready(session: AsyncSession, record: WorkItem) -> None:
    """D-154 "E1 follows d": done, but nobody to fulfil it; its group hears once, in the app.

    Not fulfilled by itself and nobody is assigned: the request says "Ready to fulfil: assign
    someone" until a person of its group takes it and fulfils it.
    """
    await record_event(
        session,
        ServiceRequestReadyToFulfil(
            work_item_id=record.id,
            type=record.type,
            display_id=record.display_id,
            status=record.status,
            status_category=record.status_category,
            group_id=record.group_id,
        ),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )


async def after_task_change(
    session: AsyncSession,
    record_id: uuid.UUID,
    *,
    source: Source,
    ticked_by: uuid.UUID | None = None,
    completed_required: bool = False,
) -> WorkItem | None:
    """Start the work on the first ticked task (D-154c); fulfil once the last is done (REQ-SR-058).

    `ticked_by` is who changed the task's status, when it was a person. `completed_required`:
    this change finished a required task, the only change that can make the request ready
    (its group hears once per completion, never again on an optional task's tick; lane B).
    """
    record = await session.get(WorkItem, record_id)
    if (
        record is None
        or record.type != WorkItemTypeCode.SERVICE_REQUEST.value
        or record.catalog_item_id is None
        or StatusCategory(record.status_category) is not StatusCategory.OPEN
    ):
        return None
    item_id = record.catalog_item_id
    tasks = await parts.tasks_of(session, record_id)
    if ticked_by is not None and any(t.from_plan and t.status == TaskStatus.DONE for t in tasks):
        record = await _start_on_first_task(session, record, ticked_by, source=source)
    planned = [t for t in tasks if t.from_plan and t.required]
    if not planned or any(t.status != TaskStatus.DONE for t in planned):
        return None
    if record.technician_id is None and completed_required:
        await _tell_ready(session, record)
    item = await service_catalog.item_decides(session, item_id)
    if record.technician_id is None or item is None or not item.auto_fulfil:
        return None
    wtype = TYPES[WorkItemTypeCode.SERVICE_REQUEST]
    cat = await config.load(session, wtype)
    if not cat.lifecycle_of(record.lifecycle).allows(record.status, WorkItemAction.RESOLVE):
        return None
    try:
        # A savepoint: when the closing rules refuse (a required resolution, open work that
        # blocks), the task's own save still stands and a technician fulfils it by hand.
        async with session.begin_nested():
            return await items.system_move(
                session,
                wtype,
                cat,
                record,
                WorkItemAction.RESOLVE,
                source=source,
                rule=FULFILMENT_RULE,
                by_requester=False,
                # Optional tasks may stay open (REQ-SR-058 counts the required ones): a "warn"
                # open-work rule is confirmed; a "block" rule still stops it.
                given=closing.MoveInput(resolution=_done_summary(planned), confirm_open_work=True),
            )
    except (ValidationFailed, Conflict, PermissionDenied):
        return None


__all__ = ["FIRST_TASK_RULE", "FULFILMENT_RULE", "after_task_change", "start_plan"]
