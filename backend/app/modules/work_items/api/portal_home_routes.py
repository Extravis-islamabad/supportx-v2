"""The portal home's summary over HTTP (WP-032 D1; REQ-PRT-002).

GET /api/v1/portal/summary   your open requests by status, approvals waiting, open tasks
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.identity_access import Subject
from app.modules.work_items.domain.portal import PortalStatus
from app.modules.work_items.service import portal_home as service
from app.shared.api.ratelimit import rate_limit

router = APIRouter(
    prefix="/portal", tags=["portal"], dependencies=[Depends(rate_limit("work_items"))]
)
SignedIn = Annotated[Subject, Depends(require_signed_in())]


class PortalStatusCount(BaseModel):
    """How many of your open requests are in one status."""

    status: PortalStatus
    count: int


class PortalSummaryOut(BaseModel):
    """The home page's counts (only your own records)."""

    open_by_status: list[PortalStatusCount] = Field(
        description="Your open incidents and service requests by the status you are told."
    )
    approvals: int = Field(description="Approvals waiting for your decision.")
    tasks: int = Field(description="Tasks you own that are not done.")


@router.get("/summary", summary="Your requests, approvals and tasks at a glance")
async def portal_summary(session: TenantSession, subject: SignedIn) -> PortalSummaryOut:
    """Counts for the portal home; refetch on your channels to keep it live (REQ-PRT-002)."""
    found = await service.summary(session, subject)
    return PortalSummaryOut(
        open_by_status=[
            PortalStatusCount(status=s, count=n)
            for s in PortalStatus
            if (n := found.open_by_status.get(s, 0))
        ],
        approvals=found.approvals,
        tasks=found.tasks,
    )


__all__ = ["router"]
