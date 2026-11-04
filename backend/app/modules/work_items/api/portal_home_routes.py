"""The portal home's summary over HTTP (WP-032 D1; REQ-PRT-002).

GET /api/v1/portal/summary   your open requests by status, approvals waiting, open tasks
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import Subject
from app.modules.work_items.domain.portal import PortalStatus
from app.modules.work_items.infra.models import WorkItemPortalSettings
from app.modules.work_items.service import portal_home as service
from app.modules.work_items.service import portal_settings
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

SearchSource = Literal["items", "articles", "announcements", "requests"]

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


class PortalSettingsOut(BaseModel):
    """The portal's own settings (D-143 defaults until the first change)."""

    search_sources: list[SearchSource] = Field(
        description="What the one search box looks through, in this order (REQ-PRT-003)."
    )
    profile_editing: bool = Field(description="Requesters may edit their own profile.")
    requester_reminders: bool = Field(description="Requesters get reminders of what waits.")
    version: int


class PortalSettingsPatch(BaseModel):
    """What to change (only what is sent)."""

    model_config = ConfigDict(extra="forbid")

    search_sources: list[SearchSource] | None = Field(default=None, min_length=1, max_length=4)
    profile_editing: bool | None = None
    requester_reminders: bool | None = None


def _settings_out(row: WorkItemPortalSettings) -> PortalSettingsOut:
    return PortalSettingsOut(
        search_sources=list(row.search_sources),  # type: ignore[arg-type]  # checked codes
        profile_editing=row.profile_editing,
        requester_reminders=row.requester_reminders,
        version=row.version,
    )


@router.get("/settings", summary="The portal's settings")
async def get_portal_settings(
    session: TenantSession, subject: SignedIn, response: Response
) -> PortalSettingsOut:
    """Anyone signed in: the portal reads its search order and switches (no secrets here)."""
    del subject
    row = await portal_settings.read(session)
    set_etag(response, row.version)
    return _settings_out(row)


@router.patch("/settings", summary="Change the portal's settings")
async def patch_portal_settings(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: PortalSettingsPatch,
    session: TenantSession,
    subject: SignedIn,
    version: ExpectedVersion,
    request: Request,
    response: Response,
    note: Annotated[AuditNote, audited("portal.settings_changed", object_type="portal_settings")],
) -> PortalSettingsOut:
    """Takes effect in open portals at once; every change is audited with old and new value."""
    before = await portal_settings.read(session)
    old = {k: getattr(before, k) for k in body.model_fields_set}
    row = await portal_settings.update(
        session,
        subject,
        expected_version=version,
        values={
            k: v for k, v in body.model_dump(include=body.model_fields_set).items() if v is not None
        },
        source=source_of(request),
    )
    changed = {
        k: (old[k], getattr(row, k)) for k in body.model_fields_set if old[k] != getattr(row, k)
    }
    note.details = {
        "changed_fields": sorted(changed),
        "old": {k: v[0] for k, v in changed.items()},
        "new": {k: v[1] for k, v in changed.items()},
    }
    set_etag(response, row.version)
    return _settings_out(row)


__all__ = ["router"]
