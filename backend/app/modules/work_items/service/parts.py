"""Tasks, worklogs and links of a work item (WP-020e; REQ-INC-067, 072, 084).

They are parts of the record: each change is in the record's history (`child_added`,
`child_changed`, `child_removed`, with the part as the field) without bumping the record's
version (ADR-026), and an event names the record so every open screen refreshes the part live.

Reading a part needs the record's view permission; changing one needs its edit permission. One
exception (REQ-INC-072 AC3, D-112): when the type allows it, a task's owner may change their
task's status without access to the record; they see the task and the record's ID and subject,
never its conversation or notes.

A link shows on both records and is recorded on both. Someone who cannot see the other record
sees that a link exists, never its ID or subject (REQ-INC-084 AC3); to make a link, both records
must be visible.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PermissionDenied
from app.modules import automation, licensing
from app.modules.identity_access import Subject
from app.modules.work_items.domain.closure import OpenItem, OpenWorkKind
from app.modules.work_items.domain.parts import (
    COMMENT_MAX,
    DESCRIPTION_MAX,
    MAX_TASKS,
    OPEN_TASK_STATUSES,
    TITLE_MAX,
    LinkKind,
    TaskStatus,
    WorklogTimes,
    moved,
    worklog_times,
)
from app.modules.work_items.domain.tasks import (
    GATED_STATUSES,
    MAX_DEPENDENCIES,
    DependencyMode,
    creates_loop,
    detail_problems,
    open_predecessors,
)
from app.modules.work_items.domain.types import TYPES, WorkItemType, WorkItemTypeCode
from app.modules.work_items.events import WorkItemPartChanged, WorkItemTaskAssigned
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemLink,
    WorkItemTask,
    WorkItemTaskDependency,
    WorkItemTypeSettings,
    WorkItemWorklog,
)
from app.modules.work_items.service import followers
from app.modules.work_items.service import stages as stage_service
from app.modules.work_items.service import work_items as items
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

RECORD_TYPE = "work_item"
_CHANGES: dict[str, Literal["added", "changed", "removed"]] = {
    "child_added": "added",
    "child_changed": "changed",
    "child_removed": "removed",
}


class TaskRepository(Repository[WorkItemTask]):
    """Tasks of the session's tenant."""

    model = WorkItemTask


class WorklogRepository(Repository[WorkItemWorklog]):
    """Worklogs of the session's tenant."""

    model = WorkItemWorklog


class LinkRepository(Repository[WorkItemLink]):
    """Links of the session's tenant."""

    model = WorkItemLink


async def _recorded(  # noqa: PLR0913, PLR0917 - the record, the part and what changed, explicit
    session: AsyncSession,
    record: WorkItem,
    part: Literal["task", "worklog", "link"],
    part_id: uuid.UUID,
    kind: Literal["child_added", "child_changed", "child_removed"],
    changes: list[Change],
    source: Source,
) -> None:
    """History on the record and the live signal, in the change's transaction."""
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind=kind,
        changes=changes,
        source=source,
    )
    task = await session.get(WorkItemTask, part_id) if part == "task" else None
    await record_event(
        session,
        WorkItemPartChanged(
            work_item_id=record.id,
            part=part,
            part_id=part_id,
            change=_CHANGES[kind],
            task_status=task.status if task is not None else None,
        ),
        aggregate_id=record.id,
    )


def _text(value: object, field: str, limit: int, problems: list[tuple[str, str]]) -> str | None:
    text = " ".join(str(value or "").split()) if field == "title" else str(value or "").strip()
    if not text:
        return None
    if len(text) > limit:
        problems.append((field, "value_too_long"))
    return text


async def _work_access(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> tuple[WorkItem, bool]:
    """Tasks and worklogs: (record, full). Full with `edit`; else an investigator (ADR-040).

    A closed or canceled change is locked (REQ-CHG-097): no task or worklog is added or changed.
    """
    try:
        record = await items.record_for_action(session, subject, wtype, "edit", record_id)
        full = True
    except PermissionDenied:
        if subject.holds(wtype.permission("view")) and await followers.is_investigator(
            session, record_id, subject.user_id
        ):
            record, full = await items.visible_record(session, subject, wtype, record_id), False
        else:
            raise
    if wtype.code is WorkItemTypeCode.CHANGE and items.is_closed(record):
        raise Conflict(code=items.RECORD_CLOSED, params={"status": record.status})
    return record, full


async def _for_work(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> WorkItem:
    """Tasks: `edit`, or an investigator of this record (ADR-040), nothing wider."""
    record, _full = await _work_access(session, subject, wtype, record_id)
    return record


async def for_work(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> WorkItem:
    """The record, if the subject may work on its parts (tasks, checklists).

    `edit`, or an investigator of it; a closed change is locked (REQ-CHG-097).
    """
    return await _for_work(session, subject, wtype, record_id)


def _own_time_only(wtype: WorkItemType, subject: Subject, owner_id: uuid.UUID | None) -> None:
    """An investigator logs, changes and removes only their own time (lane B, ADR-040).

    `owner_id` None is a new worklog without an owner, which then is the subject's own (stored
    worklogs always have an owner).
    """
    if owner_id is not None and owner_id != subject.user_id:
        raise PermissionDenied(
            params={"permission": wtype.permission("edit"), "reason": "own_worklogs_only"}
        )


# --- tasks (REQ-INC-072) --------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskCount:
    """Done over total of a record's tasks (canceled ones are not counted)."""

    done: int
    total: int


async def _tasks(session: AsyncSession, record_id: uuid.UUID) -> list[WorkItemTask]:
    rows = await session.scalars(
        select(WorkItemTask)
        .where(WorkItemTask.work_item_id == record_id, WorkItemTask.deleted_at.is_(None))
        .order_by(WorkItemTask.position, WorkItemTask.id)
    )
    return list(rows)


def count_of(tasks: list[WorkItemTask]) -> TaskCount:
    """Done over all tasks that still count (not canceled)."""
    live = [t for t in tasks if t.status != TaskStatus.CANCELED]
    return TaskCount(sum(1 for t in live if t.status == TaskStatus.DONE), len(live))


async def tasks(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> list[WorkItemTask]:
    """A record's tasks in their order."""
    await items.visible_record(session, subject, wtype, record_id)
    return await _tasks(session, record_id)


# WP-046a S1 (REQ-INC-073): a task's details, checked together with what it has now.
DETAILS = (
    "task_type",
    "scheduled_start",
    "scheduled_end",
    "actual_start",
    "actual_end",
    "estimated_minutes",
    "percent_complete",
    "extra_cost",
    "remind_before_minutes",
)


def _task_values(
    values: dict[str, Any],
    *,
    creating: bool,
    stages: frozenset[str] | None = None,
    current: WorkItemTask | None = None,
) -> dict[str, Any]:
    problems: list[tuple[str, str]] = []
    clean: dict[str, Any] = {}
    # A staged record's task belongs to one of its path's stages (REQ-CHG-088); other types
    # have none.
    if "stage" in values and values["stage"] is not None:
        if stages is None:
            problems.append(("stage", "not_allowed"))
        elif values["stage"] not in stages:
            problems.append(("stage", "invalid_choice"))
        else:
            clean["stage"] = values["stage"]
    if "title" in values or creating:
        title = _text(values.get("title"), "title", TITLE_MAX, problems)
        if title is None:
            problems.append(("title", "required"))
        clean["title"] = title
    if "description" in values:
        clean["description"] = _text(
            values["description"], "description", DESCRIPTION_MAX, problems
        )
    for name in ("owner_id", "group_id", "status", "priority", "due_at", *DETAILS):
        if name in values:
            clean[name] = values[name]
    problems += _detail_problems(clean, current, creating=creating)
    if problems:
        raise items.field_errors(problems)
    return clean


def _detail_problems(
    clean: dict[str, Any], current: WorkItemTask | None, *, creating: bool
) -> list[tuple[str, str]]:
    """The details as they will be (what it has now, with the change) checked together."""
    merged = {n: getattr(current, n) if current is not None else None for n in DETAILS}
    merged.update({n: clean[n] for n in DETAILS if n in clean})
    if "scheduled_start" in clean or "remind_before_minutes" in clean:
        clean["reminded_at"] = None  # a new start or offset reminds again (REQ-INC-073 AC2)
    return [p for p in detail_problems(merged) if creating or p[0] in clean]


_TRACKED = (
    "title",
    "status",
    "owner_id",
    "group_id",
    "priority",
    "due_at",
    "done_by",
    "stage",
    *DETAILS,
)


async def _stages_of(
    session: AsyncSession, wtype: WorkItemType, record: WorkItem
) -> frozenset[str] | None:
    """The stages of a staged record's path (None: the type has no stages)."""
    if wtype.stages is None or record.stage_path is None:
        return None
    model = await stage_service.load_model(session, wtype, record.lifecycle_version)
    return frozenset(model.path(str(record.stage_path)).stages)


def _snapshot(task: WorkItemTask) -> dict[str, Any]:
    return {name: getattr(task, name) for name in _TRACKED}


def _task_history(before: dict[str, Any] | None, after: WorkItemTask) -> list[Change]:
    """The task by title, then each changed field as `task.<field>`."""
    if before is None:
        return [Change("task", None, after.title)]
    changes = [Change("task", after.title, after.title)]
    for name in _TRACKED:
        old, new = before[name], getattr(after, name)
        if old != new:
            changes.append(Change(f"task.{name}", _json(old), _json(new)))
    return changes


def _json(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


async def create_task(  # noqa: PLR0913 - the record, the task and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    values: dict[str, Any],
    *,
    source: Source,
) -> WorkItemTask:
    """A new task at the end of the record's list."""
    record = await _for_work(session, subject, wtype, record_id)
    existing = await _tasks(session, record_id)
    if len(existing) >= MAX_TASKS:
        raise items.field_errors([("title", "too_many_items")], max=MAX_TASKS)
    stages = await _stages_of(session, wtype, record)
    clean = _task_values(values, creating=True, stages=stages)
    if stages is not None and "stage" not in clean:
        clean["stage"] = record.stage  # the stage it is in now, unless another is named
    status = clean.get("status") or TaskStatus.OPEN.value
    row = await TaskRepository(session).add(
        WorkItemTask(
            work_item_id=record.id,
            position=(existing[-1].position + 1) if existing else 0,
            **{"status": status, "priority": "normal", **clean},
            done_at=datetime.now(UTC) if status == TaskStatus.DONE else None,
        )
    )
    await _recorded(
        session, record, "task", row.id, "child_added", _task_history(None, row), source
    )
    await _assigned(session, record, row, before=None)
    return row


async def create_template_task(
    session: AsyncSession,
    record: WorkItem,
    values: dict[str, Any],
    *,
    source: Source,
    by: uuid.UUID | None,
) -> WorkItemTask:
    """A task the record's template adds as the record is made (REQ-INC-040).

    No permission check of its own: it is part of creating the record, which was checked. The
    history says the template added it (AC1: "history records their creation by the template").
    """
    del by  # the record's creator is the history's actor already
    existing = await _tasks(session, record.id)
    clean = _task_values(values, creating=True)
    row = await TaskRepository(session).add(
        WorkItemTask(
            work_item_id=record.id,
            position=(existing[-1].position + 1) if existing else 0,
            **{"status": TaskStatus.OPEN.value, "priority": "normal", **clean},
            stage=record.stage,
        )
    )
    await _recorded(
        session,
        record,
        "task",
        row.id,
        "child_added",
        [*_task_history(None, row), Change("task.from_template", old=None, new=True)],
        source,
    )
    return row


async def _assigned(
    session: AsyncSession, record: WorkItem, task: WorkItemTask, *, before: uuid.UUID | None
) -> None:
    """A task given to someone new tells them (WP-046a S1; REQ-INC-076 AC1)."""
    if task.owner_id is None or task.owner_id == before:
        return
    await record_event(
        session,
        WorkItemTaskAssigned(work_item_id=record.id, task_id=task.id, owner_id=task.owner_id),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )


async def _task(session: AsyncSession, record_id: uuid.UUID, task_id: uuid.UUID) -> WorkItemTask:
    found: WorkItemTask | None = await session.scalar(
        select(WorkItemTask).where(
            WorkItemTask.id == task_id,
            WorkItemTask.work_item_id == record_id,
            WorkItemTask.deleted_at.is_(None),
        )
    )
    if found is None:
        raise NotFound(code="work_item_task_not_found")
    return found


async def owner_access(session: AsyncSession, wtype: WorkItemType) -> bool:
    """Whether the type lets a task's owner work on it without access to the record."""
    found = await session.scalar(
        select(WorkItemTypeSettings.task_owner_access).where(
            WorkItemTypeSettings.type == wtype.code
        )
    )
    return bool(found)


async def _task_access(
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    task_id: uuid.UUID,
) -> tuple[WorkItem, WorkItemTask, bool]:
    """As `_any_task_access`, and a closed or canceled change's tasks are locked (REQ-CHG-097)."""
    record, task, full = await _any_task_access(session, subject, wtype, record_id, task_id)
    if wtype.code is WorkItemTypeCode.CHANGE and items.is_closed(record):
        raise Conflict(code=items.RECORD_CLOSED, params={"status": record.status})
    return record, task, full


async def _any_task_access(
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    task_id: uuid.UUID,
) -> tuple[WorkItem, WorkItemTask, bool]:
    """(record, task, full): full when the subject may edit the record; else the owner path.

    Anyone else gets 404, as if the record did not exist.
    """
    if await items.may(session, subject, wtype, "edit", record_id) or (
        # An investigator works the record's tasks in full (ADR-040).
        subject.holds(wtype.permission("view"))
        and await followers.is_investigator(session, record_id, subject.user_id)
    ):
        record = await items.visible_record(session, subject, wtype, record_id)
        return record, await _task(session, record_id, task_id), True
    task: WorkItemTask | None = await session.scalar(
        select(WorkItemTask).where(
            WorkItemTask.id == task_id,
            WorkItemTask.work_item_id == record_id,
            WorkItemTask.deleted_at.is_(None),
        )
    )
    parent = await session.get(WorkItem, record_id)
    if (
        task is not None
        and parent is not None
        and parent.deleted_at is None
        and task.owner_id == subject.user_id
        and await owner_access(session, wtype)
    ):
        return parent, task, False
    if await items.may(session, subject, wtype, "view", record_id):
        raise PermissionDenied(
            params={"permission": wtype.permission("edit"), "reason": "no_permission"}
        )
    raise NotFound(code="work_item_not_found")


async def update_task(  # noqa: PLR0913, PLR0917 - the task, its version, the change and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    task_id: uuid.UUID,
    values: dict[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> WorkItemTask:
    """Change a task (If-Match). A task-only owner changes the status only."""
    record, task, full = await _task_access(session, subject, wtype, record_id, task_id)
    if not full and set(values) - {"status"}:
        raise PermissionDenied(
            params={"permission": wtype.permission("edit"), "reason": "task_owner_status_only"}
        )
    clean = _task_values(
        values, creating=False, stages=await _stages_of(session, wtype, record), current=task
    )
    if clean.get("status") in GATED_STATUSES and clean["status"] != task.status:
        await _predecessors_done(session, wtype, task)
    if "status" in clean:
        done = clean["status"] == TaskStatus.DONE
        clean["done_at"] = datetime.now(UTC) if done else None
        clean["done_by"] = subject.user_id if done else None  # D-154d: "Done by <name>"
    was_done = task.status == TaskStatus.DONE
    before = _snapshot(task)
    updated = await TaskRepository(session).update(
        task.id, expected_version=expected_version, changes=clean
    )
    changes = _task_history(before, updated)
    if len(changes) > 1:  # something besides the task's name changed
        await _recorded(session, record, "task", updated.id, "child_changed", changes, source)
    await _assigned(session, record, updated, before=before["owner_id"])
    if "status" in clean and updated.workflow_instance_id is not None:
        await workflow_task_settled(session, updated)
    if "status" in clean and updated.from_plan:
        # Imported here: fulfilment uses this module's tasks (WP-030 s3, REQ-SR-058).
        from app.modules.work_items.service import fulfilment  # noqa: PLC0415 - see above

        await fulfilment.after_task_change(
            session,
            record.id,
            source=source,
            ticked_by=subject.user_id,
            # Only this change finishing a required task can make the request ready (lane B).
            completed_required=updated.required
            and updated.status == TaskStatus.DONE
            and not was_done,
        )
    return updated


async def delete_task(  # noqa: PLR0913 - the task, its version and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    task_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Remove a task (soft delete)."""
    record = await _for_work(session, subject, wtype, record_id)
    task = await _task(session, record_id, task_id)
    removed = await TaskRepository(session).soft_delete(task.id, expected_version=expected_version)
    await _recorded(
        session,
        record,
        "task",
        removed.id,
        "child_removed",
        [Change("task", removed.title, None)],
        source,
    )
    if removed.workflow_instance_id is not None:
        await workflow_task_settled(session, removed, removed_now=True)


async def move_task(  # noqa: PLR0913 - the task, the direction and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    task_id: uuid.UUID,
    *,
    by: int,
    source: Source,
) -> list[WorkItemTask]:
    """Move a task one place up (-1) or down (+1); the new order is saved for everyone."""
    record = await _for_work(session, subject, wtype, record_id)
    current = await _tasks(session, record_id)
    ids = [str(t.id) for t in current]
    if str(task_id) not in ids:
        raise NotFound(code="work_item_task_not_found")
    order = moved(ids, ids.index(str(task_id)), by)
    if order is None:
        raise items.field_errors([("by", "out_of_range")])
    by_id = {str(t.id): t for t in current}
    repository = TaskRepository(session)
    for position, key in enumerate(order):
        row = by_id[key]
        if row.position != position:
            by_id[key] = await repository.update(
                row.id, expected_version=row.version, changes={"position": position}
            )
    task = by_id[str(task_id)]
    await _recorded(
        session,
        record,
        "task",
        task.id,
        "child_changed",
        [
            Change("task", task.title, task.title),
            Change("task.position", ids.index(str(task_id)), order.index(str(task_id))),
        ],
        source,
    )
    return await _tasks(session, record_id)


def is_overdue(task: WorkItemTask, now: datetime | None = None) -> bool:
    """Open and past its due time (REQ-INC-076 AC2: marked overdue in "my tasks" and the list)."""
    return (
        task.status in OPEN_TASK_STATUSES
        and task.due_at is not None
        and task.due_at < (now or datetime.now(UTC))
    )


async def may_see_money(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> bool:
    """A task's extra cost: for those who may edit the record (the coordinator, WP-046a S1).

    Never for a task-only owner or an investigator without edit; S3 decides task and worklog cost
    visibility once for both.
    """
    return await items.may(session, subject, wtype, "edit", record_id)


async def live_tasks(session: AsyncSession, task: WorkItemTask) -> list[WorkItemTask]:
    """The other tasks of the task's record (for its blocked state)."""
    return await _tasks(session, task.work_item_id)


# --- dependencies (WP-046a S1, REQ-INC-075) -----------------------------------------------------


async def dependency_mode(session: AsyncSession, wtype: WorkItemType) -> DependencyMode:
    """Whether an open predecessor refuses a start or completion (default) or only warns."""
    found = await session.scalar(
        select(WorkItemTypeSettings.task_dependency_mode).where(
            WorkItemTypeSettings.type == wtype.code
        )
    )
    return DependencyMode(found or DependencyMode.BLOCK)


async def dependencies_of(
    session: AsyncSession, record_id: uuid.UUID
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Each task of the record and the tasks it waits for, in the order they were added."""
    rows = await session.execute(
        select(WorkItemTaskDependency.task_id, WorkItemTaskDependency.depends_on_id)
        .where(WorkItemTaskDependency.work_item_id == record_id)
        .order_by(WorkItemTaskDependency.created_at, WorkItemTaskDependency.depends_on_id)
    )
    found: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for task_id, depends_on in rows:
        found[task_id].append(depends_on)
    return dict(found)


def blocked_by(
    task: WorkItemTask, dependencies: dict[uuid.UUID, list[uuid.UUID]], tasks: list[WorkItemTask]
) -> list[uuid.UUID]:
    """The predecessors of `task` still open (shown as blocked, REQ-INC-075)."""
    statuses = {t.id: t.status for t in tasks}
    return open_predecessors(dependencies.get(task.id, []), statuses)


async def _predecessors_done(
    session: AsyncSession, wtype: WorkItemType, task: WorkItemTask
) -> None:
    """Refuse a start or completion while a predecessor is open (AC1), unless the type warns."""
    if await dependency_mode(session, wtype) is DependencyMode.WARN:
        return
    waits = (await dependencies_of(session, task.work_item_id)).get(task.id, [])
    if not waits:
        return
    others = {t.id: t for t in await _tasks(session, task.work_item_id)}
    open_ids = open_predecessors(waits, {i: t.status for i, t in others.items()})
    # A deleted predecessor no longer holds the task back.
    open_ids = [i for i in open_ids if i in others]
    if open_ids:
        first = others[open_ids[0]]
        raise Conflict(
            code="task_blocked",
            params={"task": first.title, "task_id": str(first.id), "count": len(open_ids)},
        )


async def set_dependencies(  # noqa: PLR0913, PLR0917 - the task, what it waits for, the source
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    task_id: uuid.UUID,
    depends_on: list[uuid.UUID],
    *,
    source: Source,
) -> list[uuid.UUID]:
    """Replace the tasks this task waits for: the same record's, at most 20, never a loop (AC3)."""
    record = await _for_work(session, subject, wtype, record_id)
    task = await _task(session, record_id, task_id)
    wanted = list(dict.fromkeys(depends_on))
    if len(wanted) > MAX_DEPENDENCIES:
        raise items.field_errors([("depends_on", "too_many_items")], max=MAX_DEPENDENCIES)
    siblings = {t.id: t for t in await _tasks(session, record_id)}
    if any(d not in siblings for d in wanted):
        raise items.field_errors([("depends_on", "invalid_value")])
    edges = await dependencies_of(session, record_id)
    edges.pop(task.id, None)
    if creates_loop(edges, task.id, wanted):
        raise items.field_errors([("depends_on", "dependency_loop")])
    before = (await dependencies_of(session, record_id)).get(task.id, [])
    if set(before) == set(wanted):
        return before
    await session.execute(
        delete(WorkItemTaskDependency).where(WorkItemTaskDependency.task_id == task.id)
    )
    for depends_on_id in wanted:
        session.add(
            WorkItemTaskDependency(
                tenant_id=record.tenant_id,
                task_id=task.id,
                depends_on_id=depends_on_id,
                work_item_id=record.id,
                created_by=subject.user_id,
            )
        )
    await session.flush()
    await _recorded(
        session,
        record,
        "task",
        task.id,
        "child_changed",
        [
            Change("task", task.title, task.title),
            Change(
                "task.depends_on",
                [siblings[d].title for d in before if d in siblings],
                [siblings[d].title for d in wanted],
            ),
        ],
        source,
    )
    return wanted


async def my_tasks(
    session: AsyncSession, subject: Subject, wtype: WorkItemType
) -> list[tuple[WorkItemTask, WorkItem]]:
    """Open tasks the subject owns, with their records (the task-only owner's entry point)."""
    rows = await session.execute(
        select(WorkItemTask, WorkItem)
        .join(WorkItem, WorkItem.id == WorkItemTask.work_item_id)
        .where(
            WorkItemTask.owner_id == subject.user_id,
            WorkItemTask.deleted_at.is_(None),
            WorkItemTask.status.in_(OPEN_TASK_STATUSES),
            WorkItem.type == wtype.code,
            WorkItem.deleted_at.is_(None),
        )
        .order_by(WorkItemTask.due_at.nulls_last(), WorkItemTask.created_at)
        .limit(200)
    )
    found = [(task, record) for task, record in rows.tuples()]
    if not await owner_access(session, wtype):  # without the setting, only records they see
        found = [(t, r) for t, r in found if await items.may(session, subject, wtype, "view", r.id)]
    return found


async def all_my_tasks(
    session: AsyncSession, subject: Subject
) -> list[tuple[WorkItemTask, WorkItem]]:
    """Open tasks the subject owns on every type (REQ-INC-076), due first.

    Each type licensed for the tenant, each record through its own rule (the type's view, or
    its task-owner setting), as the per-type lists do: a task on a record the person can no
    longer see is not listed (the coordinator, WP-046a S1).
    """
    found: list[tuple[WorkItemTask, WorkItem]] = []
    for wtype in TYPES.values():
        if not await licensing.has_feature(subject.tenant_id, wtype.feature):
            continue
        found += await my_tasks(session, subject, wtype)
    far = datetime.max.replace(tzinfo=UTC)
    return sorted(found, key=lambda pair: (pair[0].due_at or far, pair[0].created_at))[:200]


async def open_tasks(session: AsyncSession, record: WorkItem) -> list[OpenItem]:
    """The record's open work for the closing checks (WP-020f port)."""
    return [
        OpenItem(OpenWorkKind.TASKS, t.title)
        for t in await _tasks(session, record.id)
        if t.status in OPEN_TASK_STATUSES
    ]


async def complete_tasks(session: AsyncSession, record: WorkItem) -> None:
    """The "complete open work on close" setting: open tasks become done, each in history."""
    now = datetime.now(UTC)
    repository = TaskRepository(session)
    for open_task in await _tasks(session, record.id):
        if open_task.status in OPEN_TASK_STATUSES:
            old = open_task.status
            task = await repository.update(
                open_task.id,
                expected_version=open_task.version,
                changes={"status": TaskStatus.DONE.value, "done_at": now},
            )
            await _recorded(
                session,
                record,
                "task",
                task.id,
                "child_changed",
                [
                    Change("task", task.title, task.title),
                    Change("task.status", old, TaskStatus.DONE.value),
                ],
                "system",
            )
            if task.workflow_instance_id is not None:
                await workflow_task_settled(session, task)


# --- a workflow's task node (WP-048b S2, REQ-WF-015) ------------------------------------------


def _title(titles: dict[str, Any]) -> str:
    """A task's title: English, else the first language given (a task holds one title)."""
    chosen = titles.get("en") or next(iter(titles.values()), "")
    return str(chosen).strip()[:200]


async def open_workflow_tasks(  # noqa: PLR0913 - the node's command, explicit
    session: AsyncSession,
    record: WorkItem,
    *,
    instance_id: uuid.UUID,
    command: str,
    titles: list[dict[str, Any]],
    owner_id: uuid.UUID | None,
    group_id: uuid.UUID | None,
    due_at: datetime | None,
) -> list[WorkItemTask]:
    """The node's checklist at the end of the record's tasks, each naming its node."""
    existing = await _tasks(session, record.id)
    if len(existing) + len(titles) > MAX_TASKS:
        raise items.field_errors([("title", "too_many_items")], max=MAX_TASKS)
    position = (existing[-1].position + 1) if existing else 0
    repository = TaskRepository(session)
    made: list[WorkItemTask] = []
    for offset, titled in enumerate(titles):
        row = await repository.add(
            WorkItemTask(
                work_item_id=record.id,
                position=position + offset,
                title=_title(titled),
                owner_id=owner_id,
                group_id=group_id,
                due_at=due_at,
                status=TaskStatus.OPEN.value,
                priority="normal",
                workflow_instance_id=instance_id,
                workflow_command=command,
            )
        )
        await _recorded(
            session, record, "task", row.id, "child_added", _task_history(None, row), "workflow"
        )
        made.append(row)
    return made


async def workflow_task_settled(
    session: AsyncSession, task: WorkItemTask, *, removed_now: bool = False
) -> None:
    """A task of a node changed: all done continues the node; canceled or removed: its error.

    A result the node already took is ignored by the interpreter, so a later change of another
    task of the same checklist changes nothing.
    """
    if task.workflow_instance_id is None or task.workflow_command is None:
        return
    rows = list(
        await session.scalars(
            select(WorkItemTask).where(
                WorkItemTask.workflow_instance_id == task.workflow_instance_id,
                WorkItemTask.workflow_command == task.workflow_command,
            )
        )
    )
    gone = removed_now or any(
        r.deleted_at is not None or r.status == TaskStatus.CANCELED for r in rows
    )
    done = all(r.deleted_at is None and r.status == TaskStatus.DONE for r in rows)
    if not gone and not done:
        return
    await automation.command_finished(
        session,
        instance_id=task.workflow_instance_id,
        command=task.workflow_command,
        ok=not gone,
        error="task_canceled" if gone else None,
    )


# --- worklogs (REQ-INC-067) -----------------------------------------------------------------------


@dataclass(frozen=True)
class WorklogTotals:
    """Minutes in all, per person and per worklog type (AC3)."""

    minutes: int
    by_owner: dict[uuid.UUID, int]
    by_type: dict[str, int]


async def _worklogs(session: AsyncSession, record_id: uuid.UUID) -> list[WorkItemWorklog]:
    rows = await session.scalars(
        select(WorkItemWorklog)
        .where(WorkItemWorklog.work_item_id == record_id, WorkItemWorklog.deleted_at.is_(None))
        .order_by(WorkItemWorklog.started_at.desc(), WorkItemWorklog.id)
    )
    return list(rows)


def totals_of(rows: list[WorkItemWorklog]) -> WorklogTotals:
    """Totals of a record's worklogs."""
    by_owner: dict[uuid.UUID, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)
    for row in rows:
        by_owner[row.owner_id] += row.minutes
        by_type[row.worklog_type] += row.minutes
    return WorklogTotals(sum(r.minutes for r in rows), dict(by_owner), dict(by_type))


async def worklogs(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> list[WorkItemWorklog]:
    """A record's worklogs, newest first."""
    await items.visible_record(session, subject, wtype, record_id)
    return await _worklogs(session, record_id)


def _times(values: dict[str, Any]) -> WorklogTimes:
    found = worklog_times(values.get("started_at"), values.get("ended_at"), values.get("minutes"))
    if isinstance(found, tuple):
        raise items.field_errors([found])
    return found


def _worklog_history(row: WorkItemWorklog) -> list[Change]:
    return [
        Change(
            "worklog",
            None,
            {
                "owner_id": str(row.owner_id),
                "worklog_type": row.worklog_type,
                "minutes": row.minutes,
            },
        )
    ]


async def create_worklog(  # noqa: PLR0913 - the record, the worklog and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    values: dict[str, Any],
    *,
    source: Source,
) -> WorkItemWorklog:
    """Log time on a record; the owner defaults to the subject."""
    record, full = await _work_access(session, subject, wtype, record_id)
    if not full:
        owner = values.get("owner_id")
        _own_time_only(wtype, subject, uuid.UUID(str(owner)) if owner else None)
    times = _times(values)
    problems: list[tuple[str, str]] = []
    description = _text(values.get("description"), "description", DESCRIPTION_MAX, problems)
    if problems:
        raise items.field_errors(problems)
    row = await WorklogRepository(session).add(
        WorkItemWorklog(
            work_item_id=record.id,
            owner_id=values.get("owner_id") or subject.user_id,
            worklog_type=values["worklog_type"],
            started_at=times.started_at,
            ended_at=times.ended_at,
            minutes=times.minutes,
            description=description,
            # WP-058b S3 (0142): a staged record's worklog belongs to its stage then; set here,
            # never sent by the client (lane A's OK). Other types keep none.
            stage=record.stage if wtype.stages is not None else None,
        )
    )
    await _recorded(
        session, record, "worklog", row.id, "child_added", _worklog_history(row), source
    )
    return row


async def _worklog(
    session: AsyncSession, record_id: uuid.UUID, worklog_id: uuid.UUID
) -> WorkItemWorklog:
    found: WorkItemWorklog | None = await session.scalar(
        select(WorkItemWorklog).where(
            WorkItemWorklog.id == worklog_id,
            WorkItemWorklog.work_item_id == record_id,
            WorkItemWorklog.deleted_at.is_(None),
        )
    )
    if found is None:
        raise NotFound(code="work_item_worklog_not_found")
    return found


async def update_worklog(  # noqa: PLR0913, PLR0917 - the worklog, its version, the change and source
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    worklog_id: uuid.UUID,
    values: dict[str, Any],
    *,
    expected_version: int,
    source: Source,
) -> WorkItemWorklog:
    """Change a worklog (If-Match); the times are checked together again."""
    record, full = await _work_access(session, subject, wtype, record_id)
    row = await _worklog(session, record_id, worklog_id)
    if not full:
        _own_time_only(wtype, subject, row.owner_id)
        if values.get("owner_id"):
            _own_time_only(wtype, subject, uuid.UUID(str(values["owner_id"])))
    merged = {
        "started_at": row.started_at,
        "ended_at": row.ended_at,
        "minutes": row.minutes,
        **values,
    }
    if "minutes" in values and "ended_at" not in values:
        merged["ended_at"] = None  # a new duration moves the end
    elif "ended_at" in values and "minutes" not in values:
        merged["minutes"] = None  # a new end gives the duration
    times = _times(merged)
    changes: dict[str, Any] = {
        "started_at": times.started_at,
        "ended_at": times.ended_at,
        "minutes": times.minutes,
    }
    problems: list[tuple[str, str]] = []
    for name in ("owner_id", "worklog_type"):
        if values.get(name) is not None:
            changes[name] = values[name]
    if "description" in values:
        changes["description"] = _text(
            values["description"], "description", DESCRIPTION_MAX, problems
        )
    if problems:
        raise items.field_errors(problems)
    updated = await WorklogRepository(session).update(
        row.id, expected_version=expected_version, changes=changes
    )
    await _recorded(
        session, record, "worklog", updated.id, "child_changed", _worklog_history(updated), source
    )
    return updated


async def delete_worklog(  # noqa: PLR0913 - the worklog, its version and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    worklog_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Remove a worklog (soft delete)."""
    record, full = await _work_access(session, subject, wtype, record_id)
    row = await _worklog(session, record_id, worklog_id)
    if not full:
        _own_time_only(wtype, subject, row.owner_id)
    removed = await WorklogRepository(session).soft_delete(
        row.id, expected_version=expected_version
    )
    await _recorded(
        session,
        record,
        "worklog",
        removed.id,
        "child_removed",
        [Change("worklog", _worklog_history(removed)[0].new, None)],
        source,
    )


# --- links (REQ-INC-084) --------------------------------------------------------------------------


@dataclass(frozen=True)
class LinkView:
    """A link as one record shows it: the other record, if the subject may see it."""

    link: WorkItemLink
    other_id: uuid.UUID
    # "related"; for follows: "follows" (this record follows the other) or "followed_by";
    # for caused by: "caused_by" (this incident, by the other) or "causes" (this problem).
    relation: "Relation"
    visible: bool
    display_id: str | None
    subject_text: str | None
    other_type: WorkItemTypeCode | None = None
    # The other record is a live (not retired) known error: incidents show the marker (044b).
    other_known_error: bool = False


async def links(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> list[LinkView]:
    """Both sides of every link of the record, oldest first."""
    await items.visible_record(session, subject, wtype, record_id)
    rows = await session.scalars(
        select(WorkItemLink)
        .where(
            or_(WorkItemLink.source_id == record_id, WorkItemLink.target_id == record_id),
            WorkItemLink.kind.in_(_LISTED),
            WorkItemLink.deleted_at.is_(None),
        )
        .order_by(WorkItemLink.created_at, WorkItemLink.id)
    )
    found: list[LinkView] = []
    for link in rows:
        mine_is_source = link.source_id == record_id
        other = link.target_id if mine_is_source else link.source_id
        row = await session.get(WorkItem, other)
        # A caused-by link joins two types: the other's own permissions decide (WP-044a).
        other_type = TYPES.get(WorkItemTypeCode(row.type)) if row is not None else None
        visible = other_type is not None and await items.may(
            session, subject, other_type, "view", other
        )
        shown = row if visible else None
        found.append(
            LinkView(
                link,
                other,
                _relation(LinkKind(link.kind), mine_is_source=mine_is_source),
                visible and shown is not None,
                shown.display_id if shown is not None else None,
                shown.subject if shown is not None else None,
                other_type.code if visible and other_type is not None else None,
                shown is not None
                and shown.known_error_at is not None
                and shown.known_error_retired_at is None,
            )
        )
    return found


# The kinds this listing reads (`_relation`). Release links (WP-058a) are listed by the
# release's own parts until the cross-type relations of REQ-REL-034 join them here.
_LISTED = (
    LinkKind.RELATED.value,
    LinkKind.FOLLOWS.value,
    LinkKind.CAUSED_BY.value,
    LinkKind.MERGED_INTO.value,
)


Relation = Literal[
    "related", "follows", "followed_by", "caused_by", "causes", "merged_into", "merged_from"
]


def _relation(kind: LinkKind, *, mine_is_source: bool) -> Relation:
    """How the link reads from this record's side."""
    match kind:
        case LinkKind.RELATED:
            return "related"
        case LinkKind.FOLLOWS:
            return "follows" if mine_is_source else "followed_by"
        case LinkKind.CAUSED_BY:
            return "caused_by" if mine_is_source else "causes"
        case LinkKind.MERGED_INTO:
            return "merged_into" if mine_is_source else "merged_from"
        case _:  # never listed (_LISTED)
            msg = f"link kind {kind} is not listed here"
            raise ValueError(msg)


def _pair(record_id: uuid.UUID, other_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """A related link is stored in ID order, so A-B and B-A are one link."""
    return (record_id, other_id) if str(record_id) < str(other_id) else (other_id, record_id)


async def _link_recorded(  # noqa: PLR0913, PLR0917 - both records, the link and what happened, explicit
    session: AsyncSession,
    record: WorkItem,
    other: WorkItem,
    link: WorkItemLink,
    kind: Literal["child_added", "child_removed"],
    source: Source,
) -> None:
    """History and signals on both records (REQ-INC-084 AC1/AC2)."""
    for this, that in ((record, other), (other, record)):
        value = {"kind": link.kind, "id": str(that.id), "display_id": that.display_id}
        changes = (
            [Change("link", None, value)]
            if kind == "child_added"
            else [Change("link", value, None)]
        )
        await _recorded(session, this, "link", link.id, kind, changes, source)


async def add_link(  # noqa: PLR0913 - both records, the comment and the source, explicit
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    other_id: uuid.UUID,
    *,
    comment: str | None,
    source: Source,
) -> WorkItemLink:
    """Link two records as related (both must be visible; editing the first)."""
    record = await items.record_for_action(session, subject, wtype, "edit", record_id)
    if other_id == record_id:
        raise items.field_errors([("other_id", "cannot_link_itself")])
    try:
        other = await items.visible_record(session, subject, wtype, other_id)
    except NotFound as error:
        raise items.field_errors([("other_id", "record_not_found")]) from error
    problems: list[tuple[str, str]] = []
    clean = _text(comment, "comment", COMMENT_MAX, problems)
    source_id, target_id = _pair(record_id, other_id)
    exists = await session.scalar(
        select(func.count()).where(
            WorkItemLink.source_id == source_id,
            WorkItemLink.target_id == target_id,
            WorkItemLink.kind == LinkKind.RELATED,
            WorkItemLink.deleted_at.is_(None),
        )
    )
    if exists:
        problems.append(("other_id", "already_linked"))
    if problems:
        raise items.field_errors(problems)
    link = await LinkRepository(session).add(
        WorkItemLink(
            source_id=source_id, target_id=target_id, kind=LinkKind.RELATED.value, comment=clean
        )
    )
    await _link_recorded(session, record, other, link, "child_added", source)
    return link


_OWN_ROUTE = frozenset({LinkKind.CAUSED_BY.value, LinkKind.MERGED_INTO.value})


async def remove_link(  # noqa: PLR0913 - the record, the link, its version and the source
    session: AsyncSession,
    subject: Subject,
    wtype: WorkItemType,
    record_id: uuid.UUID,
    link_id: uuid.UUID,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Remove a link from either side; both histories say so (AC2)."""
    record = await items.record_for_action(session, subject, wtype, "edit", record_id)
    link: WorkItemLink | None = await session.scalar(
        select(WorkItemLink).where(
            WorkItemLink.id == link_id,
            or_(WorkItemLink.source_id == record_id, WorkItemLink.target_id == record_id),
            WorkItemLink.deleted_at.is_(None),
        )
    )
    if link is None:
        raise NotFound(code="work_item_link_not_found")
    if link.kind in _OWN_ROUTE:
        # A cause needs the incident's edit right (unlink), a merge its undo (WP-044b): the
        # generic delete would skip those rules.
        raise Conflict(code="link_has_own_route", params={"kind": link.kind})
    other_id = link.target_id if link.source_id == record_id else link.source_id
    other = await session.get(WorkItem, other_id)
    removed = await LinkRepository(session).soft_delete(link.id, expected_version=expected_version)
    if other is not None:
        await _link_recorded(session, record, other, removed, "child_removed", source)


async def add_follows(
    session: AsyncSession, newer: WorkItem, older: WorkItem, *, source: Source
) -> WorkItemLink:
    """`newer` follows `older` (WP-020f's follow-up record after the reopen window)."""
    link = await LinkRepository(session).add(
        WorkItemLink(source_id=newer.id, target_id=older.id, kind=LinkKind.FOLLOWS.value)
    )
    await _link_recorded(session, newer, older, link, "child_added", source)
    return link


tasks_of = _tasks
recorded = _recorded
link_recorded = _link_recorded
