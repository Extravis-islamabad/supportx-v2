"""A change's child changes and releases (WP-045d S1; REQ-CHG-096).

`GET /api/v1/changes/{id}/children` lists those you may see; `POST` makes a change or a release
part of the change (editing the change, seeing the child); `DELETE …/children/{link_id}` takes
one off. Closing the change waits for every child (the change guard).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules.identity_access import Subject
from app.modules.work_items.domain.types import CHANGE
from app.modules.work_items.service import change_links as service
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

router = APIRouter(
    prefix="/changes",
    tags=["changes"],
    dependencies=[Depends(rate_limit("work_items"))],
)
View = Annotated[Subject, Depends(require_permission(CHANGE.permission("view")))]
Edit = Annotated[Subject, Depends(require_permission(CHANGE.permission("edit")))]


class ChildIn(BaseModel):
    """The change or release to make part of this change."""

    model_config = ConfigDict(extra="forbid")

    child_id: uuid.UUID


class ChildOut(BaseModel):
    """A child change or release, as you may see it."""

    link_id: uuid.UUID
    record_id: uuid.UUID
    type: str
    display_id: str
    subject: str
    stage: str | None
    status: str
    status_category: str


@router.get("/{record_id}/children", summary="The change's child changes and releases")
async def list_children(
    record_id: uuid.UUID, session: TenantSession, subject: View
) -> list[ChildOut]:
    """Those you may see, by number; closing waits for every one."""
    _, found = await service.children(session, subject, record_id)
    return [
        ChildOut(
            link_id=link.id,
            record_id=child.id,
            type=child.type,
            display_id=child.display_id,
            subject=child.subject,
            stage=child.stage,
            status=child.status,
            status_category=child.status_category,
        )
        for link, child in found
    ]


@router.post(
    "/{record_id}/children",
    summary="Make a change or a release part of this change",
    status_code=status.HTTP_201_CREATED,
)
async def add_child(
    record_id: uuid.UUID,
    body: ChildIn,
    session: TenantSession,
    subject: Edit,
    request: Request,
) -> dict[str, uuid.UUID]:
    """One parent each, never itself or one of its own parents."""
    link = await service.add_child(
        session, subject, record_id, body.child_id, source=source_of(request)
    )
    return {"link_id": link.id}


@router.delete(
    "/{record_id}/children/{link_id}",
    summary="Take a child off the change",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_child(
    record_id: uuid.UUID,
    link_id: uuid.UUID,
    session: TenantSession,
    subject: Edit,
    request: Request,
) -> Response:
    """Kept in both records' history."""
    await service.remove_child(session, subject, record_id, link_id, source=source_of(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
