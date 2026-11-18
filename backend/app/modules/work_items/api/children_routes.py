"""Parent and child incidents over the API (WP-046b S2; REQ-INC-086).

The children show in the record's links (`GET /{id}/links`, relations `parent_of` and
`child_of`, an unseen record as a hidden line); these routes add and remove them, with edit on
both records (the service's rule).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules.identity_access import Subject
from app.modules.work_items.api.list_routes import BulkJobOut
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.service import incident_children as service
from app.shared.api.concurrency import ExpectedVersion
from app.shared.api.idempotency import Created, Idempotency
from app.shared.history import source_of

CONFLICT_409: dict[int | str, dict[str, object]] = {
    status.HTTP_409_CONFLICT: {"description": "The link changed since you read it."}
}


class IncidentChildIn(BaseModel):
    """The incident to make a child of this one."""

    child_id: uuid.UUID


class IncidentChildOut(BaseModel):
    """The new parent link (child -> parent)."""

    link_id: uuid.UUID
    child_id: uuid.UUID
    parent_id: uuid.UUID
    version: int


class ResolveChildrenIn(BaseModel):
    """The open children to resolve with the parent's resolution (at most 1,000)."""

    child_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)


class AttachChildrenIn(BaseModel):
    """Similar incidents to attach to a major incident as its children (at most 1,000)."""

    child_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)


class ResolvableChildOut(BaseModel):
    """An open child you may edit: offered the parent's resolution (REQ-INC-092)."""

    id: uuid.UUID
    display_id: str
    subject: str
    version: int


def add_children_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """`POST /{id}/children`, `DELETE /{id}/children/{link_id}` and the resolvable children."""
    edit = Annotated[Subject, Depends(require_permission(wtype.permission("edit")))]

    @router.get("/{record_id}/children/resolvable", summary="Children to resolve with this one")
    async def resolvable_children(
        record_id: uuid.UUID, session: TenantSession, subject: edit
    ) -> list[ResolvableChildOut]:
        """The open children you may edit, to resolve with this record.

        Resolving them is a bulk resolve job (each one checked again as it runs) with this
        record's resolution and `follow_up_of` set to its number.
        """
        rows = await service.open_children(session, subject, wtype, record_id)
        return [
            ResolvableChildOut(
                id=r.id, display_id=r.display_id, subject=r.subject, version=r.version
            )
            for r in rows
        ]

    @router.post(
        "/{record_id}/children",
        summary="Add a child incident",
        status_code=status.HTTP_201_CREATED,
        response_model=IncidentChildOut,
    )
    async def add_child(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: IncidentChildIn,
        session: TenantSession,
        subject: edit,
        idempotency: Idempotency,
        request: Request,
    ) -> Response:
        """One level: a parent is no child and a child has no children. Edit on both."""

        async def run() -> Created:
            link = await service.add_child(
                session, subject, wtype, record_id, body.child_id, source=source_of(request)
            )
            return Created(
                body=IncidentChildOut(
                    link_id=link.id,
                    child_id=link.source_id,
                    parent_id=link.target_id,
                    version=link.version,
                )
            )

        return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)

    @router.delete(
        "/{record_id}/children/{link_id}",
        summary="Remove a child incident",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=CONFLICT_409,
    )
    async def remove_child(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        link_id: uuid.UUID,
        version: ExpectedVersion,
        session: TenantSession,
        subject: edit,
        request: Request,
    ) -> Response:
        """From the parent's or the child's side; edit on both. Needs If-Match."""
        await service.remove_child(
            session,
            subject,
            wtype,
            record_id,
            link_id,
            expected_version=version,
            source=source_of(request),
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/{record_id}/children/resolve",
        summary="Resolve chosen children with this one's resolution",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def resolve_children(
        record_id: uuid.UUID,
        body: ResolveChildrenIn,
        session: TenantSession,
        subject: edit,
        request: Request,
    ) -> BulkJobOut:
        """A background job: each child through its own rules, with a result per child."""
        job = await service.resolve_children(
            session, subject, wtype, record_id, body.child_ids, source=source_of(request)
        )
        return BulkJobOut.of(job)

    @router.post(
        "/{record_id}/children/attach",
        summary="Attach similar incidents to a major incident as children",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def attach_children(
        record_id: uuid.UUID,
        body: AttachChildrenIn,
        session: TenantSession,
        subject: edit,
        request: Request,
    ) -> BulkJobOut:
        """A background job as you: each one checked again, with a result (and reason) per one."""
        job = await service.attach_similar(
            session, subject, wtype, record_id, body.child_ids, source=source_of(request)
        )
        return BulkJobOut.of(job)
