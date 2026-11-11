"""The portal's changes for requesters over HTTP (WP-045d S4a; REQ-CHG-109).

    GET  /api/v1/portal/changes                  own changes (or a wider reach held), open first
    GET  /api/v1/portal/changes/templates        the change forms offered to requesters
    POST /api/v1/portal/changes                  raise a change from one of them, Idempotency-Key
    GET  /api/v1/portal/changes/{id}             one: its stage, status and planned window
    GET  /api/v1/portal/changes/{id}/conversation  public replies and notes only
    POST /api/v1/portal/changes/{id}/replies     the requester's public reply

The same reach rules as the portal's incidents and requests (service/portal.py, D-129).
A requester follows the change's stage, status, planned window and public notes, and never
its plans, risk, approvals detail, outcome or private notes (AC2): those fields are simply not
in these responses. A requester who is an approver or a CAB member decides through the change's
own approval routes, which allow its approvers (`/changes/{id}/approvals/{a}/decision`; #391).
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.identity_access import PolicyService, Subject, get_policy
from app.modules.work_items.api.portal_routes import (
    PortalConversationOut,
    PortalEntryOut,
    PortalReplyIn,
    PortalTemplateOut,
)
from app.modules.work_items.api.routes import RESPONSES
from app.modules.work_items.domain.conversation import EntryKind
from app.modules.work_items.domain.portal import PortalReach
from app.modules.work_items.domain.types import CHANGE, DESCRIPTION_MAX, SUBJECT_MAX
from app.modules.work_items.service import portal as service
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.listing import ListQuery, list_query
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

router = APIRouter(
    prefix="/portal/changes",
    tags=["portal"],
    dependencies=[Depends(rate_limit("work_items"))],
    responses=RESPONSES,
)
SignedIn = Annotated[Subject, Depends(require_signed_in())]
Query_ = Annotated[
    ListQuery, Depends(list_query(service.FIELDS, extra_parameters=frozenset({"state"})))
]


class PortalChangeOut(BaseModel):
    """A change as its requester's side sees it: where it is and when, never how."""

    id: uuid.UUID
    display_id: str
    subject: str
    stage: str | None = Field(description="The stage code (labels `work_item_stage.*`).")
    status: str = Field(description="The status code (labels `work_item_status.*`).")
    status_category: str
    reach: PortalReach
    requester_id: uuid.UUID
    on_behalf_of_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    version: int


class PortalChangeDetailOut(PortalChangeOut):
    """One change with its planned window (the implementation's scheduled start and end)."""

    planned_start: datetime | None = None
    planned_end: datetime | None = None


class PortalChangePage(BaseModel):
    """One page of the requester's changes."""

    items: list[PortalChangeOut]
    next_cursor: str | None
    has_more: bool


class PortalChangeIn(BaseModel):
    """What a requester sends to raise a change: the form's own fields, nothing staff-side."""

    model_config = ConfigDict(extra="forbid")  # a staff field is refused, never ignored

    template_id: uuid.UUID | None = Field(default=None, description="Default: the first offered.")
    subject: str = Field(max_length=SUBJECT_MAX * 2)
    description: str | None = Field(
        default=None, max_length=DESCRIPTION_MAX * 2, description="Rich text (HTML), sanitised."
    )
    on_behalf_of_id: uuid.UUID | None = Field(
        default=None, description="Raise it for someone else, within the tenant's scope (403)."
    )


def _out(found: service.PortalRecord) -> PortalChangeOut:
    r = found.record
    return PortalChangeOut(
        id=r.id,
        display_id=r.display_id,
        subject=r.subject,
        stage=r.stage,
        status=r.status,
        status_category=r.status_category,
        reach=found.reach,
        requester_id=r.requester_id,
        on_behalf_of_id=r.on_behalf_of_id,
        created_at=r.created_at,
        updated_at=r.updated_at,
        version=r.version,
    )


@router.get("", summary="Your changes in the portal")
async def list_portal_changes(
    session: TenantSession,
    query: Query_,
    subject: SignedIn,
    state: Annotated[service.PortalState | None, Query(description="Open or closed.")] = None,
) -> PortalChangePage:
    """Own changes, plus those of a wider reach the person holds (REQ-CHG-109)."""
    rows, page = await service.list_records(session, subject, query, wtype=CHANGE, state=state)
    return PortalChangePage(
        items=[_out(r) for r in rows], next_cursor=page.next_cursor, has_more=page.has_more
    )


@router.get("/templates", summary="The change forms the portal offers")
async def list_portal_change_templates(
    session: TenantSession, subject: SignedIn
) -> list[PortalTemplateOut]:
    """Change templates marked for requesters (else the default), requester fields only."""
    del subject
    return [PortalTemplateOut.of(t) for t in await service.portal_templates(session, CHANGE)]


@router.post(
    "",
    summary="Raise a change in the portal",
    status_code=status.HTTP_201_CREATED,
    response_model=PortalChangeDetailOut,
)
async def create_portal_change(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: PortalChangeIn,
    session: TenantSession,
    subject: SignedIn,
    idempotency: Idempotency,
    request: Request,
    policy: Annotated[PolicyService, Depends(get_policy)],
) -> Response:
    """A new change in your name from a form offered to requesters; its ID comes back at once."""

    async def run() -> Created:
        values = body.model_dump(exclude_unset=True, exclude={"template_id"})
        found = await service.create_record(
            session,
            subject,
            values,
            template_id=body.template_id,
            source=source_of(request),
            holders=policy,
            wtype=CHANGE,
        )
        out = PortalChangeDetailOut(**_out(found).model_dump())
        return Created(
            body=out.model_dump(mode="json"),
            headers={"Location": f"/api/v1/portal/changes/{out.id}"},
        )

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.get("/{record_id}", summary="One of your changes in the portal")
async def get_portal_change(
    record_id: uuid.UUID, session: TenantSession, subject: SignedIn
) -> PortalChangeDetailOut:
    """Its stage, status and planned window; out of reach reads as not found (404)."""
    found = await service.get_record(session, subject, record_id, CHANGE)
    start, end = await service.planned_window(session, subject, record_id, CHANGE)
    return PortalChangeDetailOut(**_out(found).model_dump(), planned_start=start, planned_end=end)


@router.get("/{record_id}/conversation", summary="The public conversation of your change")
async def portal_change_conversation(
    record_id: uuid.UUID, session: TenantSession, subject: SignedIn
) -> PortalConversationOut:
    """Public replies and notes only; private notes never (AC2)."""
    entries = await service.conversation(session, subject, record_id, CHANGE)
    return PortalConversationOut(
        items=[
            PortalEntryOut(
                id=e.id,
                kind=EntryKind(e.kind),
                body=e.body,
                created_at=e.created_at,
                author_name=e.author_name,
                by_you=e.by_you,
            )
            for e in entries
        ]
    )


@router.post(
    "/{record_id}/replies",
    summary="Reply on your change",
    status_code=status.HTTP_201_CREATED,
)
async def portal_change_reply(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    record_id: uuid.UUID,
    body: PortalReplyIn,
    session: TenantSession,
    subject: SignedIn,
    request: Request,
    policy: Annotated[PolicyService, Depends(get_policy)],
) -> PortalChangeOut:
    """A public reply in your name, on your own change only."""
    await service.reply(
        session,
        subject,
        record_id,
        body=body.body,
        source=source_of(request),
        holders=policy,
        wtype=CHANGE,
    )
    return _out(await service.get_record(session, subject, record_id, CHANGE))


__all__ = ["router"]
