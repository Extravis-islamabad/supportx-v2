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
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, PermissionDenied
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
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.events import WorkItemPartChanged
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemLink,
    WorkItemTask,
    WorkItemTypeSettings,
    WorkItemWorklog,
)
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
    await record_event(
        session,
        WorkItemPartChanged(
            work_item_id=record.id,
            part=part,
            part_id=part_id,
            change=_CHANGES[kind],
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


def _task_values(values: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    problems: list[tuple[str, str]] = []
    clean: dict[str, Any] = {}
    if "title" in values or creating:
        title = _text(values.get("title"), "title", TITLE_MAX, problems)
        if title is None:
            problems.append(("title", "required"))
        clean["title"] = title
    if "description" in values:
        clean["description"] = _text(
            values["description"], "description", DESCRIPTION_MAX, problems
        )
    for name in ("owner_id", "group_id", "status", "priority", "due_at"):
        if name in values:
            clean[name] = values[name]
    if problems:
        raise items.field_errors(problems)
    return clean


_TRACKED = ("title", "status", "owner_id", "group_id", "priority", "due_at")


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
    record = await items.record_for_action(session, subject, wtype, "edit", record_id)
    existing = await _tasks(session, record_id)
    if len(existing) >= MAX_TASKS:
        raise items.field_errors([("title", "too_many_items")], max=MAX_TASKS)
    clean = _task_values(values, creating=True)
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
    return row


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
    """(record, task, full): full when the subject may edit the record; else the owner path.

    Anyone else gets 404, as if the record did not exist.
    """
    if await items.may(session, subject, wtype, "edit", record_id):
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
    clean = _task_values(values, creating=False)
    if "status" in clean:
        clean["done_at"] = datetime.now(UTC) if clean["status"] == TaskStatus.DONE else None
    before = _snapshot(task)
    updated = await TaskRepository(session).update(
        task.id, expected_version=expected_version, changes=clean
    )
    changes = _task_history(before, updated)
    if len(changes) > 1:  # something besides the task's name changed
        await _recorded(session, record, "task", updated.id, "child_changed", changes, source)
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
    record = await items.record_for_action(session, subject, wtype, "edit", record_id)
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
    record = await items.record_for_action(session, subject, wtype, "edit", record_id)
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
    record = await items.record_for_action(session, subject, wtype, "edit", record_id)
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
    record = await items.record_for_action(session, subject, wtype, "edit", record_id)
    row = await _worklog(session, record_id, worklog_id)
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
    record = await items.record_for_action(session, subject, wtype, "edit", record_id)
    row = await _worklog(session, record_id, worklog_id)
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
    # "related"; for follows: "follows" (this record follows the other) or "followed_by".
    relation: Literal["related", "follows", "followed_by"]
    visible: bool
    display_id: str | None
    subject_text: str | None


async def links(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, record_id: uuid.UUID
) -> list[LinkView]:
    """Both sides of every link of the record, oldest first."""
    await items.visible_record(session, subject, wtype, record_id)
    rows = await session.scalars(
        select(WorkItemLink)
        .where(
            or_(WorkItemLink.source_id == record_id, WorkItemLink.target_id == record_id),
            WorkItemLink.deleted_at.is_(None),
        )
        .order_by(WorkItemLink.created_at, WorkItemLink.id)
    )
    found: list[LinkView] = []
    for link in rows:
        mine_is_source = link.source_id == record_id
        other = link.target_id if mine_is_source else link.source_id
        relation: Literal["related", "follows", "followed_by"] = (
            "related"
            if link.kind == LinkKind.RELATED
            else ("follows" if mine_is_source else "followed_by")
        )
        visible = await items.may(session, subject, wtype, "view", other)
        row = await session.get(WorkItem, other) if visible else None
        found.append(
            LinkView(
                link,
                other,
                relation,
                visible and row is not None,
                row.display_id if row is not None else None,
                row.subject if row is not None else None,
            )
        )
    return found


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
