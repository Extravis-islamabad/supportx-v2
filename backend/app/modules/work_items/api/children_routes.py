"""Parent and child incidents over the API (WP-046b S2; REQ-INC-086).

The children show in the record's links (`GET /{id}/links`, relations `parent_of` and
`child_of`, an unseen record as a hidden line); these routes add and remove them, with edit on
both records (the service's rule).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules.identity_access import Subject
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.service import incident_children as service
from app.shared.api.concurrency import ExpectedVersion
from app.shared.api.idempotency import Created, Idempotency
from app.shared.history import source_of

CONFLICT_409: dict[int | str, dict[str, object]] = {
    status.HTTP_409_CONFLICT: {"description": "The link changed since you read it."}
}


class ChildIn(BaseModel):
    """The incident to make a child of this one."""

    child_id: uuid.UUID


class ChildOut(BaseModel):
    """The new parent link (child -> parent)."""

    link_id: uuid.UUID
    child_id: uuid.UUID
    parent_id: uuid.UUID
    version: int


def add_children_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """`POST /{id}/children` and `DELETE /{id}/children/{link_id}` for one type."""
    edit = Annotated[Subject, Depends(require_permission(wtype.permission("edit")))]

    @router.post(
        "/{record_id}/children",
        summary="Add a child incident",
        status_code=status.HTTP_201_CREATED,
        response_model=ChildOut,
    )
    async def add_child(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: ChildIn,
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
                body=ChildOut(
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
