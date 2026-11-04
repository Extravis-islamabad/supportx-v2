"""The portal's service requests for requesters over HTTP (WP-030 D9; REQ-SR-051, -062).

    GET /api/v1/portal/service-requests             own (or a wider reach held), open first
    GET /api/v1/portal/service-requests/{id}        one: its item and answers, plain status
    GET /api/v1/portal/service-requests/{id}/steps  fulfilment progress, internal names hidden

The same reach and plain-status rules as the portal's incidents (service/portal.py, D-129).
Approvals (respecting "hide approvals from requesters") and withdrawal use the engine's own
routes, which apply the requester's rules (`/service-requests/{id}/approvals`, `/withdraw`).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.identity_access import Subject
from app.modules.work_items.domain.portal import PortalReach, PortalStatus
from app.modules.work_items.domain.types import SERVICE_REQUEST
from app.modules.work_items.service import parts
from app.modules.work_items.service import portal as service
from app.shared.api.listing import ListQuery, list_query
from app.shared.api.ratelimit import rate_limit

router = APIRouter(
    prefix="/portal/service-requests",
    tags=["portal"],
    dependencies=[Depends(rate_limit("work_items"))],
)
SignedIn = Annotated[Subject, Depends(require_signed_in())]
Query_ = Annotated[
    ListQuery, Depends(list_query(service.FIELDS, extra_parameters=frozenset({"state"})))
]


class PortalRequestOut(BaseModel):
    """A service request as its requester's side sees it."""

    id: uuid.UUID
    display_id: str
    subject: str
    portal_status: PortalStatus
    reach: PortalReach
    requester_id: uuid.UUID
    on_behalf_of_id: uuid.UUID | None = None
    catalog_item_id: uuid.UUID | None = None
    answers: dict[str, Any] = Field(default_factory=dict)
    approval_status: str | None = None
    created_at: datetime
    updated_at: datetime
    resolution: str | None = None
    version: int


class PortalRequestPage(BaseModel):
    """One page of the requester's service requests."""

    items: list[PortalRequestOut]
    next_cursor: str | None
    has_more: bool


class PortalStepOut(BaseModel):
    """One fulfilment step: its name, unless it is internal (REQ-SR-051 AC2)."""

    position: int
    title: str | None = Field(description="None for an internal step: 'step n of m' only.")
    done: bool


class PortalStepsOut(BaseModel):
    """How far the request's fulfilment is."""

    items: list[PortalStepOut]
    done: int
    total: int


def _out(found: service.PortalRecord) -> PortalRequestOut:
    r = found.record
    return PortalRequestOut(
        id=r.id,
        display_id=r.display_id,
        subject=r.subject,
        portal_status=found.status,
        reach=found.reach,
        requester_id=r.requester_id,
        on_behalf_of_id=r.on_behalf_of_id,
        catalog_item_id=r.catalog_item_id,
        answers=dict(r.answers or {}),
        approval_status=r.approval_status,
        created_at=r.created_at,
        updated_at=r.updated_at,
        resolution=r.resolution,
        version=r.version,
    )


@router.get("", summary="Your service requests in the portal")
async def list_portal_requests(
    session: TenantSession,
    query: Query_,
    subject: SignedIn,
    state: Annotated[service.PortalState | None, Query(description="Open or closed.")] = None,
) -> PortalRequestPage:
    """Own requests, plus those of a wider reach the person holds (REQ-SR-062)."""
    rows, page = await service.list_records(
        session, subject, query, wtype=SERVICE_REQUEST, state=state
    )
    return PortalRequestPage(
        items=[_out(r) for r in rows], next_cursor=page.next_cursor, has_more=page.has_more
    )


@router.get("/{record_id}", summary="One of your service requests in the portal")
async def get_portal_request(
    record_id: uuid.UUID, session: TenantSession, subject: SignedIn
) -> PortalRequestOut:
    """Out of reach reads as not found (404), never forbidden."""
    return _out(await service.get_record(session, subject, record_id, SERVICE_REQUEST))


@router.get("/{record_id}/steps", summary="The fulfilment progress of your service request")
async def portal_request_steps(
    record_id: uuid.UUID, session: TenantSession, subject: SignedIn
) -> PortalStepsOut:
    """The plan's steps in order; an internal one shows no name (REQ-SR-051 AC2)."""
    await service.get_record(session, subject, record_id, SERVICE_REQUEST)  # 404 out of reach
    planned = [t for t in await parts.tasks_of(session, record_id) if t.from_plan]
    live = [t for t in planned if t.status != "canceled"]
    return PortalStepsOut(
        items=[
            PortalStepOut(
                position=i + 1, title=None if t.internal else t.title, done=t.status == "done"
            )
            for i, t in enumerate(live)
        ],
        done=sum(t.status == "done" for t in live),
        total=len(live),
    )


__all__ = ["router"]
