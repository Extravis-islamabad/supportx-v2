"""The tenant's approval settings over HTTP (D-146; WP-048b S2).

    GET   /api/v1/approvals/settings   the chair who breaks an exact majority split, if any
    PATCH /api/v1/approvals/settings   set or clear the chair (If-Match; audited)

Reading: any signed-in staff screen may show who the chair is (no secrets). Changing needs the
service desk configuration right (the service checks it).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import Subject
from app.modules.work_items.infra.models import WorkItemApprovalSettings
from app.modules.work_items.service import approval_settings
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.ratelimit import rate_limit
from app.shared.history import source_of

router = APIRouter(
    prefix="/approvals", tags=["approvals"], dependencies=[Depends(rate_limit("work_items"))]
)
SignedIn = Annotated[Subject, Depends(require_signed_in())]


class ApprovalSettingsOut(BaseModel):
    """The tenant's approval settings (no chair until one is set)."""

    chair_user_id: uuid.UUID | None = Field(
        description="Breaks an exact majority split in an approval level (D-146); none: it rejects."
    )
    version: int


class ApprovalSettingsPatch(BaseModel):
    """What to change (only what is sent; null clears the chair)."""

    model_config = ConfigDict(extra="forbid")

    chair_user_id: uuid.UUID | None = None


def _out(row: WorkItemApprovalSettings) -> ApprovalSettingsOut:
    return ApprovalSettingsOut(chair_user_id=row.chair_user_id, version=row.version)


@router.get("/settings", summary="The approval settings")
async def get_approval_settings(
    session: TenantSession, subject: SignedIn, response: Response
) -> ApprovalSettingsOut:
    """Who the chair is, if any."""
    del subject
    row = await approval_settings.read(session)
    set_etag(response, row.version)
    return _out(row)


@router.patch("/settings", summary="Set or clear the approval chair")
async def patch_approval_settings(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: ApprovalSettingsPatch,
    session: TenantSession,
    subject: SignedIn,
    version: ExpectedVersion,
    request: Request,
    response: Response,
    note: Annotated[
        AuditNote, audited("approvals.settings_changed", object_type="approval_settings")
    ],
) -> ApprovalSettingsOut:
    """Takes effect for the next decision; every change is audited with the old and new chair."""
    before = (await approval_settings.read(session)).chair_user_id
    row = await approval_settings.update(
        session,
        subject,
        expected_version=version,
        values=body.model_dump(include=body.model_fields_set),
        source=source_of(request),
    )
    if row.chair_user_id != before:
        note.details = {
            "changed_fields": ["chair_user_id"],
            "old": {"chair_user_id": str(before) if before else None},
            "new": {"chair_user_id": str(row.chair_user_id) if row.chair_user_id else None},
        }
    set_etag(response, row.version)
    return _out(row)


__all__ = ["router"]
