"""Tasks, worklogs and links over HTTP (WP-020e; REQ-INC-067, 072, 084).

`/my-tasks` is a collection route (mounted before `/{record_id}`); the rest hang off a record.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

from app.core.authorization import require_permission, require_signed_in
from app.core.database import TenantSession
from app.modules.identity_access import Subject
from app.modules.work_items.domain.parts import (
    COMMENT_MAX,
    DESCRIPTION_MAX,
    TITLE_MAX,
    LinkKind,
    TaskPriority,
    TaskStatus,
    WorklogType,
)
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.infra.models import WorkItem, WorkItemTask, WorkItemWorklog
from app.modules.work_items.service import parts as service
from app.shared.api.concurrency import ExpectedVersion, etag_for, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.history import source_of

CONFLICT_409: dict[int | str, dict[str, object]] = {
    409: {"description": "The version is stale; the problem names what changed."}
}


class WorkItemTaskIn(BaseModel):
    """A new task."""

    title: str = Field(max_length=TITLE_MAX * 2)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX * 2)
    owner_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    status: TaskStatus = TaskStatus.OPEN
    priority: TaskPriority = TaskPriority.NORMAL
    due_at: datetime | None = None


class WorkItemTaskPatch(BaseModel):
    """Fields to change; the ones left out keep their value."""

    title: str | None = Field(default=None, max_length=TITLE_MAX * 2)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX * 2)
    owner_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_at: datetime | None = None


class WorkItemTaskOut(BaseModel):
    """One task of a record."""

    id: uuid.UUID
    work_item_id: uuid.UUID
    title: str
    description: str | None
    owner_id: uuid.UUID | None
    group_id: uuid.UUID | None
    status: TaskStatus
    priority: TaskPriority
    due_at: datetime | None
    done_at: datetime | None
    position: int
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, row: WorkItemTask) -> "WorkItemTaskOut":
        """From a row."""
        return cls.model_validate(row, from_attributes=True)


class WorkItemTasksOut(BaseModel):
    """A record's tasks in their order, and "done / total" (canceled ones not counted)."""

    items: list[WorkItemTaskOut]
    done: int
    total: int


class WorkItemTaskMoveIn(BaseModel):
    """Move the task one place up or down."""

    direction: Literal["up", "down"]


class WorkItemMyTaskOut(BaseModel):
    """A task you own, with the record it belongs to."""

    task: WorkItemTaskOut
    work_item_id: uuid.UUID
    display_id: str
    subject: str


class WorkItemWorklogIn(BaseModel):
    """Time spent: a start and an end or a duration (in minutes); both must agree if sent."""

    owner_id: uuid.UUID | None = Field(default=None, description="Defaults to you.")
    worklog_type: WorklogType
    started_at: datetime | None = None
    ended_at: datetime | None = None
    minutes: int | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX * 2)


class WorkItemWorklogPatch(BaseModel):
    """Fields to change; a new end recomputes the duration, a new duration the end."""

    owner_id: uuid.UUID | None = None
    worklog_type: WorklogType | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    minutes: int | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX * 2)


class WorkItemWorklogOut(BaseModel):
    """One worklog."""

    id: uuid.UUID
    owner_id: uuid.UUID
    worklog_type: WorklogType
    started_at: datetime
    ended_at: datetime
    minutes: int
    description: str | None
    version: int
    created_by: uuid.UUID | None

    @classmethod
    def of(cls, row: WorkItemWorklog) -> "WorkItemWorklogOut":
        """From a row."""
        return cls.model_validate(row, from_attributes=True)


class WorkItemMinutesBy(BaseModel):
    """Minutes of one person or one worklog type."""

    key: str
    minutes: int


class WorkItemWorklogsOut(BaseModel):
    """A record's worklogs, newest first, with totals per person and per type (AC3)."""

    items: list[WorkItemWorklogOut]
    minutes: int
    by_owner: list[WorkItemMinutesBy]
    by_type: list[WorkItemMinutesBy]


class WorkItemLinkIn(BaseModel):
    """Link another record as related."""

    other_id: uuid.UUID
    comment: str | None = Field(default=None, max_length=COMMENT_MAX * 2)


class WorkItemLinkOut(BaseModel):
    """A link as this record shows it; `other` is empty when you cannot see that record."""

    id: uuid.UUID
    kind: LinkKind
    relation: Literal["related", "follows", "followed_by"]
    other_id: uuid.UUID | None = Field(description="Only when you may see the other record.")
    other_display_id: str | None
    other_subject: str | None
    comment: str | None
    version: int
    created_at: datetime


def _tasks_out(rows: list[WorkItemTask]) -> WorkItemTasksOut:
    count = service.count_of(rows)
    return WorkItemTasksOut(
        items=[WorkItemTaskOut.of(r) for r in rows], done=count.done, total=count.total
    )


def _worklogs_out(rows: list[WorkItemWorklog]) -> WorkItemWorklogsOut:
    totals = service.totals_of(rows)
    return WorkItemWorklogsOut(
        items=[WorkItemWorklogOut.of(r) for r in rows],
        minutes=totals.minutes,
        by_owner=[WorkItemMinutesBy(key=str(k), minutes=v) for k, v in totals.by_owner.items()],
        by_type=[WorkItemMinutesBy(key=k, minutes=v) for k, v in totals.by_type.items()],
    )


def add_parts_collection_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """`/my-tasks` (before `/{record_id}`)."""
    SignedIn = Annotated[Subject, Depends(require_signed_in())]  # noqa: N806 - type alias

    @router.get("/my-tasks", summary="Open tasks you own")
    async def my_tasks(session: TenantSession, subject: SignedIn) -> list[WorkItemMyTaskOut]:
        """With the record each belongs to; a task-only owner (D-111) starts here."""
        found: list[tuple[WorkItemTask, WorkItem]] = await service.my_tasks(session, subject, wtype)
        return [
            WorkItemMyTaskOut(
                task=WorkItemTaskOut.of(task),
                work_item_id=record.id,
                display_id=record.display_id,
                subject=record.subject,
            )
            for task, record in found
        ]


def add_parts_routes(router: APIRouter, wtype: WorkItemType) -> None:  # noqa: C901 - one route per operation
    """Tasks, worklogs and links of one record."""
    perm = wtype.permission
    View = Annotated[Subject, Depends(require_permission(perm("view")))]  # noqa: N806 - type alias
    SignedIn = Annotated[Subject, Depends(require_signed_in())]  # noqa: N806 - type alias

    # --- tasks ------------------------------------------------------------------------------------

    @router.get("/{record_id}/tasks", summary="Tasks of a record")
    async def list_tasks(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> WorkItemTasksOut:
        """In their order, with "done / total"."""
        return _tasks_out(await service.tasks(session, subject, wtype, record_id))

    @router.post(
        "/{record_id}/tasks",
        summary="Add a task",
        status_code=status.HTTP_201_CREATED,
        response_model=WorkItemTaskOut,
    )
    async def create_task(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: WorkItemTaskIn,
        session: TenantSession,
        subject: View,
        idempotency: Idempotency,
        request: Request,
    ) -> Response:
        """At the end of the list; needs the record's edit permission."""

        async def run() -> Created:
            row = await service.create_task(
                session,
                subject,
                wtype,
                record_id,
                body.model_dump(mode="python"),
                source=source_of(request),
            )
            return Created(body=WorkItemTaskOut.of(row), headers={"ETag": etag_for(row.version)})

        return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)

    @router.patch("/{record_id}/tasks/{task_id}", summary="Change a task", responses=CONFLICT_409)
    async def update_task(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        task_id: uuid.UUID,
        body: WorkItemTaskPatch,
        version: ExpectedVersion,
        session: TenantSession,
        subject: SignedIn,
        request: Request,
        response: Response,
    ) -> WorkItemTaskOut:
        """Needs If-Match. A task-only owner (D-111) changes the status only."""
        row = await service.update_task(
            session,
            subject,
            wtype,
            record_id,
            task_id,
            body.model_dump(mode="python", exclude_unset=True),
            expected_version=version,
            source=source_of(request),
        )
        set_etag(response, row.version)
        return WorkItemTaskOut.of(row)

    @router.delete(
        "/{record_id}/tasks/{task_id}",
        summary="Remove a task",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=CONFLICT_409,
    )
    async def delete_task(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        task_id: uuid.UUID,
        version: ExpectedVersion,
        session: TenantSession,
        subject: View,
        request: Request,
    ) -> Response:
        """Needs If-Match."""
        await service.delete_task(
            session,
            subject,
            wtype,
            record_id,
            task_id,
            expected_version=version,
            source=source_of(request),
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/{record_id}/tasks/{task_id}/move", summary="Move a task up or down")
    async def move_task(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        task_id: uuid.UUID,
        body: WorkItemTaskMoveIn,
        session: TenantSession,
        subject: View,
        request: Request,
    ) -> WorkItemTasksOut:
        """One place; the new order is saved for everyone (REQ-INC-072 AC2)."""
        rows = await service.move_task(
            session,
            subject,
            wtype,
            record_id,
            task_id,
            by=-1 if body.direction == "up" else 1,
            source=source_of(request),
        )
        return _tasks_out(rows)

    # --- worklogs ---------------------------------------------------------------------------------

    @router.get("/{record_id}/worklogs", summary="Worklogs of a record")
    async def list_worklogs(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> WorkItemWorklogsOut:
        """Newest first, with totals per person and per type."""
        return _worklogs_out(await service.worklogs(session, subject, wtype, record_id))

    @router.post(
        "/{record_id}/worklogs",
        summary="Log time",
        status_code=status.HTTP_201_CREATED,
        response_model=WorkItemWorklogOut,
    )
    async def create_worklog(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: WorkItemWorklogIn,
        session: TenantSession,
        subject: View,
        idempotency: Idempotency,
        request: Request,
    ) -> Response:
        """Needs the record's edit permission. The end cannot be before the start."""

        async def run() -> Created:
            row = await service.create_worklog(
                session,
                subject,
                wtype,
                record_id,
                body.model_dump(mode="python"),
                source=source_of(request),
            )
            return Created(body=WorkItemWorklogOut.of(row), headers={"ETag": etag_for(row.version)})

        return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)

    @router.patch(
        "/{record_id}/worklogs/{worklog_id}", summary="Change a worklog", responses=CONFLICT_409
    )
    async def update_worklog(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        worklog_id: uuid.UUID,
        body: WorkItemWorklogPatch,
        version: ExpectedVersion,
        session: TenantSession,
        subject: View,
        request: Request,
        response: Response,
    ) -> WorkItemWorklogOut:
        """Needs If-Match."""
        row = await service.update_worklog(
            session,
            subject,
            wtype,
            record_id,
            worklog_id,
            body.model_dump(mode="python", exclude_unset=True),
            expected_version=version,
            source=source_of(request),
        )
        set_etag(response, row.version)
        return WorkItemWorklogOut.of(row)

    @router.delete(
        "/{record_id}/worklogs/{worklog_id}",
        summary="Remove a worklog",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=CONFLICT_409,
    )
    async def delete_worklog(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        worklog_id: uuid.UUID,
        version: ExpectedVersion,
        session: TenantSession,
        subject: View,
        request: Request,
    ) -> Response:
        """Needs If-Match."""
        await service.delete_worklog(
            session,
            subject,
            wtype,
            record_id,
            worklog_id,
            expected_version=version,
            source=source_of(request),
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # --- links ------------------------------------------------------------------------------------

    @router.get("/{record_id}/links", summary="Links of a record")
    async def list_links(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> list[WorkItemLinkOut]:
        """Both directions; a record you cannot see shows as a link without its ID or subject."""
        return [
            WorkItemLinkOut(
                id=v.link.id,
                kind=LinkKind(v.link.kind),
                relation=v.relation,
                other_id=v.other_id if v.visible else None,
                other_display_id=v.display_id,
                other_subject=v.subject_text,
                comment=v.link.comment,
                version=v.link.version,
                created_at=v.link.created_at,
            )
            for v in await service.links(session, subject, wtype, record_id)
        ]

    @router.post(
        "/{record_id}/links",
        summary="Link a related record",
        status_code=status.HTTP_201_CREATED,
        response_model=WorkItemLinkOut,
    )
    async def create_link(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: WorkItemLinkIn,
        session: TenantSession,
        subject: View,
        idempotency: Idempotency,
        request: Request,
    ) -> Response:
        """Both records must be visible to you; the link shows and is recorded on both."""

        async def run() -> Created:
            link = await service.add_link(
                session,
                subject,
                wtype,
                record_id,
                body.other_id,
                comment=body.comment,
                source=source_of(request),
            )
            other = await session.get(WorkItem, body.other_id)
            return Created(
                body=WorkItemLinkOut(
                    id=link.id,
                    kind=LinkKind(link.kind),
                    relation="related",
                    other_id=body.other_id,
                    other_display_id=other.display_id if other else None,
                    other_subject=other.subject if other else None,
                    comment=link.comment,
                    version=link.version,
                    created_at=link.created_at,
                )
            )

        return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)

    @router.delete(
        "/{record_id}/links/{link_id}",
        summary="Remove a link",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=CONFLICT_409,
    )
    async def delete_link(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        link_id: uuid.UUID,
        version: ExpectedVersion,
        session: TenantSession,
        subject: View,
        request: Request,
    ) -> Response:
        """From either side; both histories say so. Needs If-Match."""
        await service.remove_link(
            session,
            subject,
            wtype,
            record_id,
            link_id,
            expected_version=version,
            source=source_of(request),
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
