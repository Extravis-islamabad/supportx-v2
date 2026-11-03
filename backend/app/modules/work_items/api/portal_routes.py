"""The portal's incidents for requesters over HTTP (WP-028; ~/Desktop/wp-028-plan.md D1).

    GET /api/v1/portal/incidents            "My requests": own, or one reach as a filter
    GET /api/v1/portal/incidents/{id}       one record in the viewer's reach

Only signed-in people; what they see is decided in `service/portal.py` (the one scope check).
Responses carry the allow-listed fields only: a field the record's template hides, and every
staff-only field, is absent, never null-with-a-value-elsewhere.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.identity_access import Subject
from app.modules.work_items.api.routes import RESPONSES
from app.modules.work_items.domain.portal import PortalReach, PortalStatus
from app.modules.work_items.service import portal as service
from app.shared.api.listing import ListQuery, list_query
from app.shared.api.ratelimit import rate_limit

SignedIn = Annotated[Subject, Depends(require_signed_in())]
Query_ = Annotated[
    ListQuery,
    Depends(list_query(service.FIELDS, extra_parameters=frozenset({"reach", "state", "q"}))),
]


class PortalIncidentOut(BaseModel):
    """An incident as its requester's side sees it (fields the template hides are absent)."""

    id: uuid.UUID
    display_id: str
    subject: str
    portal_status: PortalStatus
    reach: PortalReach = Field(description="Why you see it: own, or a wider reach you hold.")
    requester_id: uuid.UUID
    on_behalf_of_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    resolution: str | None = None
    version: int
    description: str | None = None
    category_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    impact: str | None = None
    urgency: str | None = None
    impact_details: str | None = None


class PortalIncidentPage(BaseModel):
    """One page of "My requests"."""

    items: list[PortalIncidentOut]
    next_cursor: str | None
    has_more: bool
    estimated_total: int | None = None


def _out(found: service.PortalRecord) -> PortalIncidentOut:
    return PortalIncidentOut.model_validate(found.values())


router = APIRouter(
    prefix="/portal/incidents",
    tags=["portal"],
    dependencies=[Depends(rate_limit("work_items"))],
    responses=RESPONSES,
)


@router.get(
    "",
    summary="Your incidents in the portal",
    response_model_exclude_unset=True,
)
async def list_portal_incidents(  # noqa: PLR0913, PLR0917 - FastAPI dependencies and query options
    session: TenantSession,
    query: Query_,
    subject: SignedIn,
    reach: Annotated[
        PortalReach | None, Query(description="Only one reach (e.g. reports).")
    ] = None,
    state: Annotated[service.PortalState | None, Query(description="Open or closed.")] = None,
    q: Annotated[str | None, Query(max_length=service.SEARCH_MAX)] = None,
) -> PortalIncidentPage:
    """Own incidents, plus those of a wider reach the person holds (REQ-PRT-007)."""
    rows, page = await service.list_records(
        session, subject, query, only=reach, state=state, search=q
    )
    return PortalIncidentPage(
        items=[_out(r) for r in rows],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        estimated_total=page.estimated_total,
    )


@router.get(
    "/{record_id}",
    summary="One of your incidents in the portal",
    response_model_exclude_unset=True,
)
async def get_portal_incident(
    session: TenantSession, subject: SignedIn, record_id: uuid.UUID
) -> PortalIncidentOut:
    """The record as the requester's side sees it; 404 when out of reach."""
    return _out(await service.get_record(session, subject, record_id))


__all__ = ["router"]
