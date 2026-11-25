"""Fulfilment from the catalog item's plan (WP-030 s3, plan D8; REQ-SR-046, -058, -060).

On approval, or at submission when no approval is needed, the item's plan becomes the
request's tasks, in order (history names each one). When the last required plan task is done
and the item fulfils automatically, the request moves to "fulfilled" by itself (history:
automatic, rule `fulfilment`). Open fulfilment tasks then block closing through WP-020f's open
work check, as any task does. A rejection creates none (REQ-SR-060).
"""

import html
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, PermissionDenied, ValidationFailed
from app.modules import automation, service_catalog
from app.modules.identity_access import UserType, person_placement
from app.modules.organization import users_in_groups
from app.modules.work_items.domain.lifecycle import DefaultStatus, StatusCategory, WorkItemAction
from app.modules.work_items.domain.parts import TaskPriority, TaskStatus
from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.events import ServiceRequestReadyToFulfil
from app.modules.work_items.infra.models import WorkItem, WorkItemTask, WorkItemTaskDependency
from app.modules.work_items.service import catalogue as config
from app.modules.work_items.service import closing, parts
from app.modules.work_items.service import work_items as items
from app.shared.conditions import matches
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

TECHNICIAN = UserType.TECHNICIAN.value  # of the desk: an owner who is not gets task-only access
# A plan step's owner kinds (service_catalog's TaskOwnerKind codes, plain values across modules).
OWNER_PERSON, OWNER_MANAGER = "person", "requested_for_manager"
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
    """The item's plan as the request's tasks, after any it already has (REQ-SR-046 AC1).

    WP-047a S5: a step whose condition does not hold makes no task (REQ-SR-048); its fields and
    kind go on the task (REQ-SR-049, -056); its owner by kind is resolved, and an owner who is
    not a technician gets that task alone, task-only (REQ-SR-050; condition 1); its
    `waits_for` become the task's dependencies (REQ-SR-047), and only a task with nothing to wait
    for tells its owner now, the rest when their last predecessor completes (`can_start`).
    """
    if item is not None and item.workflow_id is not None:
        await _start_workflow(session, record, item.workflow_id, source=source)
    if item is None or not item.plan:
        return []
    existing = await parts.tasks_of(session, record.id)
    position = (existing[-1].position + 1) if existing else 0
    facts = _plan_facts(record)
    made: list[WorkItemTask] = []
    by_key: dict[str, WorkItemTask] = {}
    for step in item.plan:
        if step.condition is not None and not matches(step.condition, facts):
            continue
        owner_id = await _step_owner(session, record, step)
        task = await parts.TaskRepository(session).add(
            WorkItemTask(
                work_item_id=record.id,
                title=_title(dict(step.title)),
                owner_id=owner_id,
                group_id=step.group_id,
                status=TaskStatus.OPEN.value,
                priority=TaskPriority.NORMAL.value,
                position=position,
                from_plan=True,
                required=step.required,
                internal=step.internal,
                plan_key=step.key,
                fields=[dict(f) for f in step.fields] or None,
                field_values={},
                kind=step.kind,
                task_only=await _outside_owner(session, step, owner_id),
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
        if step.key is not None:
            by_key[step.key] = task
    waiting = await _plan_dependencies(session, record, item, by_key)
    for task in made:
        if task.id not in waiting:  # REQ-SR-047 AC1: the rest hear when they can start
            await parts.tell_owner(session, record, task)
    return made


async def _start_workflow(
    session: AsyncSession, record: WorkItem, workflow_id: uuid.UUID, *, source: Source
) -> None:
    """The item's fulfilment workflow starts when its plan would (REQ-SR-053; WP-047a S5).

    As the workflow's run-as identity. One it can no longer run (switched off, unpublished,
    already running) never undoes the approval: the record's history says why, labelled.
    """
    try:
        await automation.start_workflow(
            session, workflow_id=workflow_id, record_type=record.type, record_id=record.id
        )
    except Conflict as refused:
        await record_changes(
            session,
            record_type=items.RECORD_TYPE,
            record_id=record.id,
            version=record.version,
            kind="updated",
            changes=[Change("fulfilment_workflow", None, str(workflow_id))],
            source=source,
            reason=refused.code,
            subtype=record.type,
        )


def _plan_facts(record: WorkItem) -> dict[str, Any]:
    """What a step's condition reads: the answers and the quantity (as S2a's stages)."""
    return {**dict(record.answers or {}), "quantity": record.quantity}


async def _step_owner(
    session: AsyncSession, record: WorkItem, step: service_catalog.PlanStep
) -> uuid.UUID | None:
    """Who the step's task goes to (REQ-SR-050): a person, the manager, a person answer."""
    kind = step.owner_kind
    if kind is None or kind == OWNER_PERSON:
        return step.owner_id
    if kind == OWNER_MANAGER:
        person = record.on_behalf_of_id or record.requester_id
        return (await person_placement(session, person)).manager_id if person else None
    answer = (record.answers or {}).get(step.question_key or "")
    try:
        return uuid.UUID(str(answer)) if answer else None
    except ValueError:
        return None


async def _outside_owner(
    session: AsyncSession, step: service_catalog.PlanStep, owner_id: uuid.UUID | None
) -> bool:
    """An owner by kind who is not a technician gets this task alone (the coordinator's 1)."""
    if step.owner_kind is None or owner_id is None:
        return False
    return (await person_placement(session, owner_id)).user_type != TECHNICIAN


async def _plan_dependencies(
    session: AsyncSession,
    record: WorkItem,
    item: service_catalog.RequestItem,
    by_key: dict[str, WorkItemTask],
) -> set[uuid.UUID]:
    """Each step's `waits_for` as its task's dependencies; the tasks that wait (REQ-SR-047).

    A predecessor whose condition did not hold made no task, so nothing waits for it.
    """
    waiting: set[uuid.UUID] = set()
    for step in item.plan:
        task = by_key.get(step.key or "")
        if task is None:
            continue
        for key in step.waits_for:
            before = by_key.get(key)
            if before is None:
                continue
            session.add(
                WorkItemTaskDependency(
                    tenant_id=record.tenant_id,
                    task_id=task.id,
                    depends_on_id=before.id,
                    work_item_id=record.id,
                )
            )
            waiting.add(task.id)
    await session.flush()
    return waiting


async def replan_conditions(session: AsyncSession, record: WorkItem, *, source: Source) -> None:
    """Changed answers before fulfilment starts add or drop conditional tasks (REQ-SR-048 AC2).

    Only while no plan task is in progress or done (the coordinator's Q4); after that the change
    is recorded only. A step whose condition now holds gains its task; one that no longer holds
    loses its open task, unless work was done on it (worklogs or field values): then it is kept
    and flagged for a person (`needs_review`; the coordinator's condition 3). Each with history.
    """
    if record.catalog_item_id is None:
        return
    item = await service_catalog.item_decides(session, record.catalog_item_id)
    if item is None or not any(step.condition is not None for step in item.plan):
        return
    tasks = [t for t in await parts.tasks_of(session, record.id) if t.from_plan]
    if any(t.status in STARTED_TASKS for t in tasks):
        return  # fulfilment has started: the change is recorded only
    facts = _plan_facts(record)
    by_key = {t.plan_key: t for t in tasks if t.plan_key and t.status != TaskStatus.CANCELED}
    for step in item.plan:
        if step.condition is None or step.key is None:
            continue
        holds = matches(step.condition, facts)
        task = by_key.get(step.key)
        if holds and task is None:
            await _add_step(session, record, step, source=source)
        elif not holds and task is not None:
            await _drop_step(session, record, task, source=source)


STARTED_TASKS = frozenset({TaskStatus.IN_PROGRESS.value, TaskStatus.DONE.value})


async def _add_step(
    session: AsyncSession, record: WorkItem, step: service_catalog.PlanStep, *, source: Source
) -> None:
    existing = await parts.tasks_of(session, record.id)
    task = await parts.TaskRepository(session).add(
        WorkItemTask(
            work_item_id=record.id,
            title=_title(dict(step.title)),
            owner_id=await _step_owner(session, record, step),
            group_id=step.group_id,
            status=TaskStatus.OPEN.value,
            priority=TaskPriority.NORMAL.value,
            position=(existing[-1].position + 1) if existing else 0,
            from_plan=True,
            required=step.required,
            internal=step.internal,
            plan_key=step.key,
            fields=[dict(f) for f in step.fields] or None,
            field_values={},
            kind=step.kind,
        )
    )
    task.task_only = await _outside_owner(session, step, task.owner_id)
    await parts.recorded(
        session, record, "task", task.id, "child_added", [Change("task", None, task.title)], source
    )
    await parts.tell_owner(session, record, task)


async def _drop_step(
    session: AsyncSession, record: WorkItem, task: WorkItemTask, *, source: Source
) -> None:
    if task.field_values or await parts.has_worklogs(session, record.id, task.owner_id):
        if not task.needs_review:  # kept: a person decides (the coordinator's condition 3)
            task.needs_review = True
            await session.flush()
            await parts.recorded(
                session,
                record,
                "task",
                task.id,
                "child_changed",
                [Change("task.needs_review", old=False, new=True)],
                source,
            )
        return
    task.status = TaskStatus.CANCELED.value
    task.version += 1
    await session.flush()
    await parts.recorded(
        session,
        record,
        "task",
        task.id,
        "child_changed",
        [Change("task.status", TaskStatus.OPEN.value, TaskStatus.CANCELED.value)],
        source,
    )


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
    lifecycle = cat.lifecycle_for(record)
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
    if not cat.lifecycle_for(record).allows(record.status, WorkItemAction.RESOLVE):
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
