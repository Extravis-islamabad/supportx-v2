"""Tasks, worklogs and links over HTTP (WP-020e; REQ-INC-067, 072, 084).

`/my-tasks` is a collection route (mounted before `/{record_id}`); the rest hang off a record.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import require_permission, require_signed_in
from app.core.database import TenantSession
from app.modules.audit import audited
from app.modules.identity_access import Subject
from app.modules.organization import base_currency
from app.modules.work_items.domain.parts import (
    COMMENT_MAX,
    COST_NOTE_MAX,
    COSTS_MAX,
    DESCRIPTION_MAX,
    TITLE_MAX,
    LinkKind,
    TaskPriority,
    TaskStatus,
    WorklogType,
)
from app.modules.work_items.domain.types import WorkItemType, WorkItemTypeCode
from app.modules.work_items.infra.models import (
    WorkItem,
    WorkItemTask,
    WorkItemTaskTemplate,
    WorkItemTimer,
    WorkItemWorklog,
    WorkItemWorklogCost,
)
from app.modules.work_items.service import parts as service
from app.modules.work_items.service import task_templates, timers
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
    stage: str | None = Field(
        default=None, max_length=40, description="Staged types: its stage (default: the current)."
    )
    # WP-046a S1 (REQ-INC-073): the task's details; an end before its start is refused (AC1).
    task_type: str | None = Field(default=None, max_length=40)
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    estimated_minutes: int | None = Field(default=None, ge=0, le=525600)
    percent_complete: int | None = Field(default=None, ge=0, le=100)
    extra_cost: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    remind_before_minutes: int | None = Field(
        default=None, ge=0, le=10080, description="Remind the owner this long before the start."
    )


class WorkItemTaskPatch(BaseModel):
    """Fields to change; the ones left out keep their value."""

    title: str | None = Field(default=None, max_length=TITLE_MAX * 2)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX * 2)
    owner_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_at: datetime | None = None
    stage: str | None = Field(default=None, max_length=40)
    # WP-046a S1 (REQ-INC-073): the task's details; an end before its start is refused (AC1).
    task_type: str | None = Field(default=None, max_length=40)
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    estimated_minutes: int | None = Field(default=None, ge=0, le=525600)
    percent_complete: int | None = Field(default=None, ge=0, le=100)
    extra_cost: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    remind_before_minutes: int | None = Field(
        default=None, ge=0, le=10080, description="Remind the owner this long before the start."
    )


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
    done_by: uuid.UUID | None = Field(default=None, description="Who ticked it done (D-154d).")
    stage: str | None = Field(default=None, description="Staged types: the stage it is for.")
    position: int
    # WP-030 s3: made by the catalog item's fulfilment plan; required to fulfil; internal.
    from_plan: bool = False
    required: bool = True
    internal: bool = False
    task_type: str | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    estimated_minutes: int | None = None
    percent_complete: int | None = None
    extra_cost: Decimal | None = Field(
        default=None, description="Shown to those who may edit the record only."
    )
    remind_before_minutes: int | None = None
    depends_on: list[uuid.UUID] = Field(
        default_factory=list, description="Tasks of the same record this one waits for."
    )
    blocked_by: list[uuid.UUID] = Field(
        default_factory=list, description="Those still open: the task shows as blocked."
    )
    overdue: bool = Field(default=False, description="Open and past its due time.")
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(
        cls,
        row: WorkItemTask,
        *,
        depends_on: list[uuid.UUID] | None = None,
        blocked_by: list[uuid.UUID] | None = None,
        money: bool = True,
    ) -> "WorkItemTaskOut":
        """From a row, with its dependencies; the cost only when `money` (may edit the record)."""
        out = cls.model_validate(row, from_attributes=True)
        out.depends_on = list(depends_on or [])
        out.blocked_by = list(blocked_by or [])
        out.overdue = service.is_overdue(row)
        if not money:
            out.extra_cost = None
        return out


class WorkItemTasksOut(BaseModel):
    """A record's tasks in their order, and "done / total" (canceled ones not counted)."""

    items: list[WorkItemTaskOut]
    done: int
    total: int


class WorkItemTaskDependenciesIn(BaseModel):
    """The tasks of the same record this task waits for (replaces the list)."""

    depends_on: list[uuid.UUID] = Field(max_length=20)


class TaskTemplateTaskIO(BaseModel):
    """One task a task template adds."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=TITLE_MAX * 2)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX * 2)
    task_type: str | None = Field(default=None, max_length=40)
    priority: TaskPriority = TaskPriority.NORMAL
    estimated_minutes: int | None = Field(default=None, ge=0, le=525600)


class TaskTemplateIn(BaseModel):
    """A new task template: one task or a set of up to 20 (REQ-INC-074)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=400)
    description: str | None = Field(default=None, max_length=4000)
    tasks: list[TaskTemplateTaskIO] = Field(min_length=1, max_length=20)


class TaskTemplatePatch(BaseModel):
    """What to change; `disabled` true stops offering it (AC2)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=400)
    description: str | None = Field(default=None, max_length=4000)
    tasks: list[TaskTemplateTaskIO] | None = Field(default=None, min_length=1, max_length=20)
    disabled: bool | None = None


class TaskTemplateOut(BaseModel):
    """A task template of the type."""

    id: uuid.UUID
    name: str
    description: str | None
    tasks: list[TaskTemplateTaskIO]
    disabled: bool
    version: int

    @classmethod
    def of(cls, row: WorkItemTaskTemplate) -> "TaskTemplateOut":
        """From a row."""
        return cls(
            id=row.id,
            name=row.name,
            description=row.description,
            tasks=[TaskTemplateTaskIO.model_validate(t) for t in row.tasks],
            disabled=row.disabled_at is not None,
            version=row.version,
        )


class FromTemplateIn(BaseModel):
    """Add a task template's tasks to the record."""

    template_id: uuid.UUID


class WorkItemTaskMoveIn(BaseModel):
    """Move the task one place up or down."""

    direction: Literal["up", "down"]


class WorkItemMyTaskOut(BaseModel):
    """A task you own, with the record it belongs to."""

    task: WorkItemTaskOut
    work_item_id: uuid.UUID
    display_id: str
    subject: str


Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]


class WorkItemWorklogCostIn(BaseModel):
    """An other cost (REQ-INC-068), in the base currency or paid in another.

    In the base currency: `amount`. In another: `original_amount`, `original_currency` and the
    `exchange_rate` to the base currency; the amount is then computed, to the cent (no automatic
    rates).
    """

    amount: Money | None = None
    original_amount: Money | None = None
    original_currency: str | None = Field(default=None, min_length=3, max_length=3)
    exchange_rate: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=8)
    note: str | None = Field(default=None, max_length=COST_NOTE_MAX * 2)


class WorkItemWorklogCostOut(BaseModel):
    """An other cost as stored, in the base currency."""

    id: uuid.UUID
    amount: Decimal
    original_amount: Decimal | None
    original_currency: str | None
    exchange_rate: Decimal | None
    note: str | None


class WorkItemWorklogIn(BaseModel):
    """Time spent: a start and an end or a duration (in minutes); both must agree if sent."""

    owner_id: uuid.UUID | None = Field(default=None, description="Defaults to you.")
    worklog_type: WorklogType
    started_at: datetime | None = None
    ended_at: datetime | None = None
    minutes: int | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX * 2)
    billable: bool = Field(default=False, description="Time the customer is charged for.")
    costs: list[WorkItemWorklogCostIn] = Field(default_factory=list, max_length=COSTS_MAX)


class WorkItemWorklogPatch(BaseModel):
    """Fields to change; a new end recomputes the duration, a new duration the end."""

    owner_id: uuid.UUID | None = None
    worklog_type: WorklogType | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    minutes: int | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX * 2)
    billable: bool | None = None
    draft: Literal[False] | None = Field(
        default=None, description="False confirms a timer's draft (REQ-INC-069 AC2)."
    )
    costs: list[WorkItemWorklogCostIn] | None = Field(
        default=None, max_length=COSTS_MAX, description="Replaces all the worklog's other costs."
    )


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
    stage: str | None = Field(
        default=None, description="A staged record's stage when it was logged (WP-058b S3)."
    )
    billable: bool = False
    draft: bool = Field(
        default=False, description="A timer's time saved on close, counted once confirmed."
    )
    money_hidden: bool = Field(
        default=False, description="You may not see costs here: the cost fields are empty."
    )
    cost_rate: Decimal | None = Field(
        default=None, description="The owner's cost per hour when the time started (a snapshot)."
    )
    technician_cost: Decimal | None = None
    costs: list[WorkItemWorklogCostOut] = Field(default_factory=list)

    @classmethod
    def of(
        cls,
        row: WorkItemWorklog,
        costs: list[WorkItemWorklogCost] | None = None,
        *,
        money: bool = True,
    ) -> "WorkItemWorklogOut":
        """From a row; its costs only when `money` (the type's cost right, REQ-INC-068 AC2)."""
        out = cls.model_validate(row, from_attributes=True)
        if money:
            out.costs = [
                WorkItemWorklogCostOut.model_validate(c, from_attributes=True) for c in costs or []
            ]
        else:
            out.money_hidden, out.cost_rate, out.technician_cost = True, None, None
        return out


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
    billable_minutes: int = 0
    non_billable_minutes: int = 0
    money_hidden: bool = False
    currency: str | None = Field(default=None, description="The base currency of the costs.")
    technician_cost: Decimal | None = None
    other_cost: Decimal | None = None
    total_cost: Decimal | None = None


class WorkItemLinkIn(BaseModel):
    """Link another record as related."""

    other_id: uuid.UUID
    comment: str | None = Field(default=None, max_length=COMMENT_MAX * 2)


class WorkItemLinkOut(BaseModel):
    """A link as this record shows it; `other` is empty when you cannot see that record."""

    id: uuid.UUID
    kind: LinkKind
    relation: service.Relation
    other_id: uuid.UUID | None = Field(description="Only when you may see the other record.")
    other_type: WorkItemTypeCode | None = Field(
        default=None, description="The other record's type, when you may see it (WP-044a)."
    )
    other_display_id: str | None
    other_subject: str | None
    other_known_error: bool = Field(
        default=False, description="The other record is a known error (problems, WP-044b)."
    )
    comment: str | None
    version: int
    created_at: datetime


def _tasks_out(
    rows: list[WorkItemTask],
    dependencies: dict[uuid.UUID, list[uuid.UUID]] | None = None,
    *,
    money: bool = True,
) -> WorkItemTasksOut:
    count = service.count_of(rows)
    deps = dependencies or {}
    return WorkItemTasksOut(
        items=[
            WorkItemTaskOut.of(
                r,
                depends_on=deps.get(r.id, []),
                blocked_by=service.blocked_by(r, deps, rows),
                money=money,
            )
            for r in rows
        ],
        done=count.done,
        total=count.total,
    )


def _worklogs_out(
    rows: list[WorkItemWorklog],
    costs: dict[uuid.UUID, list[WorkItemWorklogCost]],
    *,
    money: bool,
    currency: str,
) -> WorkItemWorklogsOut:
    totals = service.totals_of(rows, costs)
    return WorkItemWorklogsOut(
        items=[WorkItemWorklogOut.of(r, costs.get(r.id), money=money) for r in rows],
        minutes=totals.minutes,
        by_owner=[WorkItemMinutesBy(key=str(k), minutes=v) for k, v in totals.by_owner.items()],
        by_type=[WorkItemMinutesBy(key=k, minutes=v) for k, v in totals.by_type.items()],
        billable_minutes=totals.billable_minutes,
        non_billable_minutes=totals.non_billable_minutes,
        money_hidden=not money,
        currency=currency if money else None,
        technician_cost=totals.technician_cost if money else None,
        other_cost=totals.other_cost if money else None,
        total_cost=totals.total_cost if money else None,
    )


async def _worklog_out(
    session: AsyncSession, subject: Subject, wtype: WorkItemType, row: WorkItemWorklog
) -> WorkItemWorklogOut:
    """One worklog with its costs, masked without the cost right."""
    costs = await service.worklog_costs(session, row.work_item_id)
    money = await service.may_see_money(session, subject, wtype, row.work_item_id)
    return WorkItemWorklogOut.of(row, costs.get(row.id), money=money)


class WorkItemTimerIn(BaseModel):
    """Start your timer; an optional note of what you are on."""

    comment: str | None = Field(default=None, max_length=COMMENT_MAX * 2)


class WorkItemTimerOut(BaseModel):
    """Your running timer on a record (only ever yours, REQ-INC-069)."""

    id: uuid.UUID
    work_item_id: uuid.UUID
    started_at: datetime
    comment: str | None
    auto_started: bool
    version: int

    @classmethod
    def of(cls, row: WorkItemTimer) -> "WorkItemTimerOut":
        """From a row."""
        return cls.model_validate(row, from_attributes=True)


class WorkItemTimerStoppedOut(BaseModel):
    """What a stopped timer prefills a new worklog with; nothing is logged until it is saved."""

    started_at: datetime
    ended_at: datetime
    minutes: int
    comment: str | None


class MyTimerOut(BaseModel):
    """One of your running timers, with its record (the header's list)."""

    timer: WorkItemTimerOut
    work_item_id: uuid.UUID
    record_type: WorkItemTypeCode
    display_id: str
    subject: str


class AllMyTaskOut(WorkItemMyTaskOut):
    """A task you own on any work item type, with its record's type (REQ-INC-076)."""

    record_type: WorkItemTypeCode


my_tasks_router = APIRouter(prefix="/my-tasks", tags=["work_items"])


@my_tasks_router.get("", summary="Your open tasks on every type")
async def all_my_tasks(
    session: TenantSession, subject: Annotated[Subject, Depends(require_signed_in())]
) -> list[AllMyTaskOut]:
    """Due first, overdue marked; only records you may still see (or your task-owner access)."""
    return [
        AllMyTaskOut(
            task=WorkItemTaskOut.of(task, money=False),  # cost stays on the record
            work_item_id=record.id,
            display_id=record.display_id,
            subject=record.subject,
            record_type=WorkItemTypeCode(record.type),
        )
        for task, record in await service.all_my_tasks(session, subject)
    ]


my_timers_router = APIRouter(prefix="/my-timers", tags=["work_items"])


@my_timers_router.get("", summary="Your running timers on every type")
async def all_my_timers(
    session: TenantSession, subject: Annotated[Subject, Depends(require_signed_in())]
) -> list[MyTimerOut]:
    """Oldest first; only records you may still see (REQ-INC-069: shown on every screen)."""
    return [
        MyTimerOut(
            timer=WorkItemTimerOut.of(timer),
            work_item_id=record.id,
            record_type=WorkItemTypeCode(record.type),
            display_id=record.display_id,
            subject=record.subject,
        )
        for timer, record in await timers.mine(session, subject)
    ]


def add_parts_collection_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """`/my-tasks` and `/task-templates` (before `/{record_id}`)."""
    SignedIn = Annotated[Subject, Depends(require_signed_in())]  # noqa: N806 - type alias
    View = Annotated[Subject, Depends(require_permission(wtype.permission("view")))]  # noqa: N806 - type alias
    Admin = Annotated[  # noqa: N806 - type alias
        Subject, Depends(require_permission("config.service_desk", "settings.manage"))
    ]
    audit = wtype.code.value

    @router.get("/task-templates", summary="Task templates offered")
    async def offered_task_templates(
        session: TenantSession, subject: View
    ) -> list[TaskTemplateOut]:
        """The enabled task templates, by name (a disabled one is not offered, AC2)."""
        del subject
        rows = await task_templates.list_templates(session, wtype, include_disabled=False)
        return [TaskTemplateOut.of(r) for r in rows]

    @router.get("/task-templates/all", summary="Every task template (admins)")
    async def all_task_templates(session: TenantSession, subject: Admin) -> list[TaskTemplateOut]:
        """Disabled ones too, for the settings screen."""
        del subject
        rows = await task_templates.list_templates(session, wtype, include_disabled=True)
        return [TaskTemplateOut.of(r) for r in rows]

    @router.post(
        "/task-templates",
        summary="Add a task template",
        status_code=status.HTTP_201_CREATED,
        response_model=TaskTemplateOut,
        dependencies=[
            audited(f"{audit}.task_template_created", object_type=f"{audit}_task_template")
        ],
    )
    async def create_task_template(
        body: TaskTemplateIn, session: TenantSession, subject: Admin, idempotency: Idempotency
    ) -> Response:
        """A name and its tasks (REQ-INC-074)."""
        del subject

        async def run() -> Created:
            row = await task_templates.create_template(session, wtype, body.model_dump(mode="json"))
            return Created(body=TaskTemplateOut.of(row))

        return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)

    @router.patch(
        "/task-templates/{template_id}",
        summary="Change a task template",
        responses=CONFLICT_409,
        dependencies=[
            audited(
                f"{audit}.task_template_changed",
                object_type=f"{audit}_task_template",
                object_param="template_id",
            )
        ],
    )
    async def update_task_template(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        template_id: uuid.UUID,
        body: TaskTemplatePatch,
        version: ExpectedVersion,
        session: TenantSession,
        subject: Admin,
        response: Response,
    ) -> TaskTemplateOut:
        """Needs If-Match."""
        del subject
        row = await task_templates.update_template(
            session,
            wtype,
            template_id,
            body.model_dump(mode="json", include=body.model_fields_set),
            expected_version=version,
        )
        set_etag(response, row.version)
        return TaskTemplateOut.of(row)

    @router.get("/my-tasks", summary="Open tasks you own")
    async def my_tasks(session: TenantSession, subject: SignedIn) -> list[WorkItemMyTaskOut]:
        """With the record each belongs to; a task-only owner (D-112) starts here."""
        found: list[tuple[WorkItemTask, WorkItem]] = await service.my_tasks(session, subject, wtype)
        return [
            WorkItemMyTaskOut(
                task=WorkItemTaskOut.of(task, money=False),  # cost stays on the record
                work_item_id=record.id,
                display_id=record.display_id,
                subject=record.subject,
            )
            for task, record in found
        ]


def add_parts_routes(router: APIRouter, wtype: WorkItemType) -> None:  # noqa: C901, PLR0915 - one route per operation
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
        rows = await service.tasks(session, subject, wtype, record_id)
        return _tasks_out(
            rows,
            await service.dependencies_of(session, record_id),
            money=await service.may_see_money(session, subject, wtype, record_id),
        )

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
        """Needs If-Match. A task-only owner (D-112) changes the status only."""
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
        siblings = await service.dependencies_of(session, record_id)
        return WorkItemTaskOut.of(
            row,
            depends_on=siblings.get(row.id, []),
            blocked_by=service.blocked_by(row, siblings, await service.live_tasks(session, row)),
            money=await service.may_see_money(session, subject, wtype, record_id),
        )

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
        return _tasks_out(rows, await service.dependencies_of(session, record_id))

    @router.post(
        "/{record_id}/tasks/from-template",
        summary="Add a task template's tasks",
        status_code=status.HTTP_201_CREATED,
        response_model=WorkItemTasksOut,
    )
    async def tasks_from_template(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: FromTemplateIn,
        session: TenantSession,
        subject: View,
        request: Request,
        idempotency: Idempotency,
    ) -> Response:
        """At the end of the list, each ready to edit (REQ-INC-074 AC1); needs edit."""

        async def run() -> Created:
            await task_templates.add_from_template(
                session, subject, wtype, record_id, body.template_id, source=source_of(request)
            )
            rows = await service.tasks(session, subject, wtype, record_id)
            return Created(body=_tasks_out(rows, await service.dependencies_of(session, record_id)))

        return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)

    @router.put(
        "/{record_id}/tasks/{task_id}/dependencies",
        summary="Set the tasks this task waits for",
    )
    async def set_dependencies(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        task_id: uuid.UUID,
        body: WorkItemTaskDependenciesIn,
        session: TenantSession,
        subject: View,
        request: Request,
    ) -> WorkItemTasksOut:
        """The same record's tasks, at most 20; a loop is refused (REQ-INC-075 AC3)."""
        await service.set_dependencies(
            session,
            subject,
            wtype,
            record_id,
            task_id,
            body.depends_on,
            source=source_of(request),
        )
        rows = await service.tasks(session, subject, wtype, record_id)
        return _tasks_out(rows, await service.dependencies_of(session, record_id))

    # --- your timer (WP-046a S3, REQ-INC-069) ----------------------------------------------------

    @router.get("/{record_id}/timer", summary="Your timer on this record")
    async def my_timer(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> WorkItemTimerOut | None:
        """Yours only, or null."""
        row = await timers.mine_on(session, subject, wtype, record_id)
        return None if row is None else WorkItemTimerOut.of(row)

    @router.post(
        "/{record_id}/timer",
        summary="Start your timer",
        status_code=status.HTTP_201_CREATED,
        responses=CONFLICT_409,
        response_model=WorkItemTimerOut,
    )
    async def start_timer(
        record_id: uuid.UUID,
        body: WorkItemTimerIn,
        session: TenantSession,
        subject: View,
        idempotency: Idempotency,
    ) -> Response:
        """As logging time: the record's edit right, or an investigator. One running per record.

        Idempotency-Key (audit #19): a retried start replays the first answer, never a
        `timer_running` refusal for the timer it just started.
        """

        async def run() -> Created:
            row = await timers.start(session, subject, wtype, record_id, comment=body.comment)
            return Created(WorkItemTimerOut.of(row), {})

        return await idempotency.run(
            {"record_id": str(record_id), **body.model_dump(mode="json")},
            run,
            status_code=status.HTTP_201_CREATED,
        )

    @router.post("/{record_id}/timer/stop", summary="Stop your timer", responses=CONFLICT_409)
    async def stop_timer(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> WorkItemTimerStoppedOut:
        """Ends it and returns the worklog to prefill; log it to keep the time."""
        stopped = await timers.stop(session, subject, wtype, record_id)
        return WorkItemTimerStoppedOut(
            started_at=stopped.started_at,
            ended_at=stopped.ended_at,
            minutes=stopped.minutes,
            comment=stopped.comment,
        )

    @router.delete(
        "/{record_id}/timer",
        summary="Discard your timer",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=CONFLICT_409,
    )
    async def discard_timer(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> Response:
        """Ends it without logging anything."""
        await timers.discard(session, subject, wtype, record_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/{record_id}/timer/auto", summary="Start your timer if the type does so")
    async def auto_start_timer(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> WorkItemTimerOut | None:
        """The record page calls it when it opens (null when nothing started).

        With the type's setting on, a record you are the technician of starts your timer once,
        never again after it ran.
        """
        row = await timers.auto_start(session, subject, wtype, record_id)
        return None if row is None else WorkItemTimerOut.of(row)

    # --- worklogs ---------------------------------------------------------------------------------

    @router.get("/{record_id}/worklogs", summary="Worklogs of a record")
    async def list_worklogs(
        record_id: uuid.UUID, session: TenantSession, subject: View
    ) -> WorkItemWorklogsOut:
        """Newest first, with totals per person and per type; costs with the cost right."""
        rows = await service.worklogs(session, subject, wtype, record_id)
        return _worklogs_out(
            rows,
            await service.worklog_costs(session, record_id),
            money=await service.may_see_money(session, subject, wtype, record_id),
            currency=await base_currency(session),
        )

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
            out = await _worklog_out(session, subject, wtype, row)
            return Created(body=out, headers={"ETag": etag_for(row.version)})

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
        return await _worklog_out(session, subject, wtype, row)

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
                other_known_error=v.other_known_error,
                other_type=v.other_type,
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
