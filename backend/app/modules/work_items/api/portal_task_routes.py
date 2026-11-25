"""A person's own fulfilment tasks in the portal (WP-047a S5; REQ-SR-050).

    GET   /api/v1/portal/tasks            the open tasks a plan gave you, task-only
    GET   /api/v1/portal/tasks/{id}       one of them: its name, fields and values
    PATCH /api/v1/portal/tasks/{id}       start or complete it, fill in its fields (If-Match)

The coordinator's condition 1: a task given to someone outside the desk opens that task alone,
never its request: no answers, no conversation, no other task; only the request's reference.
Closing or reassigning the task ends that access (404 from then on, as if it did not exist).
The change itself goes through the same task service as the console (P2).
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, JsonValue

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.identity_access import Subject
from app.modules.work_items.api.parts_routes import WorkItemTaskFieldOut
from app.modules.work_items.domain.types import SERVICE_REQUEST
from app.modules.work_items.infra.models import WorkItemTask
from app.modules.work_items.service import parts
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

router = APIRouter(
    prefix="/portal/tasks", tags=["portal"], dependencies=[Depends(rate_limit("work_items"))]
)
SignedIn = Annotated[Subject, Depends(require_signed_in())]


class PortalTaskOut(BaseModel):
    """One of your tasks: this task alone and the request's reference (condition 1)."""

    id: uuid.UUID
    work_item_id: uuid.UUID
    request_ref: str = Field(description="The request's reference (SR-1042), nothing more.")
    title: str
    status: str
    kind: str = Field(description="task, or asset_handover.")
    fields: list[WorkItemTaskFieldOut] = Field(default_factory=list)
    field_values: dict[str, JsonValue] = Field(default_factory=dict)
    due_at: str | None = None
    version: int

    @classmethod
    def of(cls, task: WorkItemTask, ref: str) -> "PortalTaskOut":
        return cls(
            id=task.id,
            work_item_id=task.work_item_id,
            request_ref=ref,
            title=task.title,
            status=task.status,
            kind=task.kind,
            fields=[WorkItemTaskFieldOut.model_validate(f) for f in task.fields or []],
            field_values=dict(task.field_values or {}),
            due_at=task.due_at.isoformat() if task.due_at else None,
            version=task.version,
        )


class PortalTasksOut(BaseModel):
    """Your open task-only tasks, oldest first."""

    items: list[PortalTaskOut]


class PortalTaskPatch(BaseModel):
    """What a task's owner may change: its status, its fields, a hand-over's asset."""

    status: Literal["in_progress", "done"] | None = None
    field_values: dict[str, JsonValue] | None = None
    asset_id: uuid.UUID | None = None


@router.get("", summary="Your fulfilment tasks")
async def list_portal_tasks(session: TenantSession, subject: SignedIn) -> PortalTasksOut:
    """The open tasks a request's plan gave you, each alone (REQ-SR-050)."""
    found = await parts.task_only_tasks(session, subject)
    return PortalTasksOut(items=[PortalTaskOut.of(t, ref) for t, ref in found])


@router.get("/{task_id}", summary="One of your fulfilment tasks")
async def get_portal_task(
    task_id: uuid.UUID, session: TenantSession, subject: SignedIn, response: Response
) -> PortalTaskOut:
    """The task alone; 404 when it is not yours, closed or reassigned."""
    task, ref = await parts.task_only_task(session, subject, task_id)
    set_etag(response, task.version)
    return PortalTaskOut.of(task, ref)


@router.patch("/{task_id}", summary="Work on one of your fulfilment tasks")
async def update_portal_task(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    task_id: uuid.UUID,
    body: PortalTaskPatch,
    version: ExpectedVersion,
    session: TenantSession,
    subject: SignedIn,
    request: Request,
    response: Response,
) -> PortalTaskOut:
    """Needs If-Match. A required field left empty refuses completing it (REQ-SR-049 AC1)."""
    task, ref = await parts.task_only_task(session, subject, task_id)
    updated = await parts.update_task(
        session,
        subject,
        SERVICE_REQUEST,
        task.work_item_id,
        task.id,
        body.model_dump(mode="python", exclude_unset=True),
        expected_version=version,
        source=source_of(request),
    )
    set_etag(response, updated.version)
    return PortalTaskOut.of(updated, ref)


__all__ = ["router"]
