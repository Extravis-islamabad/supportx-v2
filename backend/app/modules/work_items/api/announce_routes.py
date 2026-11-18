"""Announcing from an incident over the API (WP-046b S4, REQ-INC-129).

- GET  /incidents/{id}/announcements                     the ones made from it you may see
- POST /incidents/{id}/announcements                     announce (Idempotency-Key: one per
                                                         dialog opening; a retry returns the same)
- POST /incidents/{id}/announcements/{aid}/end           end one made from it

The announcements module checks the text, the audience against the actor's scope, and who may
publish; an actor who may not publish leaves a draft for someone who may.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules.announcements import Announced
from app.modules.audit import RequestFacts
from app.modules.identity_access import PolicyService, Subject, get_policy
from app.modules.work_items.domain.types import WorkItemType
from app.modules.work_items.service import incident_announcements as service
from app.shared.api.idempotency import Created, Idempotency
from app.shared.history import source_of


class IncidentAnnounceIn(BaseModel):
    """The announcement, as the actor wrote it (the announcements module checks every field)."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=200)
    body: str = Field(max_length=20_000, description="Plain text; line breaks are kept.")
    severity: str = Field(default="info", description="An announcement severity code.")
    audience: str = Field(default="everyone", description="everyone, sites or groups.")
    site_ids: list[uuid.UUID] = Field(default_factory=list)
    group_ids: list[uuid.UUID] = Field(default_factory=list)
    show_as_banner: bool = True
    publish_until: datetime | None = None
    publish: bool = Field(
        default=True, description="Publish now when you may; otherwise it stays a draft."
    )


class IncidentAnnouncementOut(BaseModel):
    """An announcement made from the incident: IDs, title and status only."""

    id: uuid.UUID
    display_id: str
    title: str
    status: str


class IncidentAnnouncementEndIn(BaseModel):
    """Why it ends (optional; kept in the announcement's own history)."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


def _out(made: Announced) -> IncidentAnnouncementOut:
    return IncidentAnnouncementOut(
        id=made.id, display_id=made.display_id, title=made.title, status=made.status
    )


def add_announce_routes(router: APIRouter, wtype: WorkItemType) -> None:
    """The routes for incidents (edit to announce; the announcement's own rights to end)."""
    edit = Annotated[Subject, Depends(require_permission(wtype.permission("edit")))]
    view = Annotated[Subject, Depends(require_permission(wtype.permission("view")))]
    policy = Annotated[PolicyService, Depends(get_policy)]

    @router.get("/{record_id}/announcements", summary="Announcements made from an incident")
    async def announcements(
        record_id: uuid.UUID, session: TenantSession, subject: view
    ) -> list[IncidentAnnouncementOut]:
        """Only the ones you may see in the announcements module; the others are left out."""
        return [_out(a) for a in await service.linked(session, subject, record_id)]

    @router.post(
        "/{record_id}/announcements",
        summary="Announce from an incident",
        status_code=status.HTTP_201_CREATED,
        response_model=IncidentAnnouncementOut,
    )
    async def announce(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        body: IncidentAnnounceIn,
        session: TenantSession,
        subject: edit,
        holders: policy,
        idempotency: Idempotency,
        request: Request,
    ) -> Response:
        """Needs announcements.manage; send an Idempotency-Key (one per dialog opening)."""

        async def run() -> Created:
            values = body.model_dump(exclude={"publish"}, exclude_none=True)
            made = await service.announce(
                session,
                subject,
                record_id,
                values=values,
                publish=body.publish,
                source=source_of(request),
                holders=holders,
                facts=RequestFacts.of(request),
            )
            return Created(body=_out(made))

        return await idempotency.run({"announce_from": str(record_id), **body.model_dump()}, run)

    @router.post(
        "/{record_id}/announcements/{announcement_id}/end",
        summary="End an announcement made from an incident",
    )
    async def end_announcement(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        record_id: uuid.UUID,
        announcement_id: uuid.UUID,
        body: IncidentAnnouncementEndIn,
        session: TenantSession,
        subject: view,
        request: Request,
    ) -> IncidentAnnouncementOut:
        """Archived through the announcements module, with your rights there; 404 otherwise."""
        ended = await service.end(
            session,
            subject,
            record_id,
            announcement_id,
            reason=body.reason,
            source=source_of(request),
        )
        return _out(ended)
