"""Connector defaults HTTP API under /api/v1/integrations/connector-settings (WP-040, D-041).

Read and saved with `integrations.manage_email` (MANAGE; every connector category's defaults).
Saving takes If-Match with the version read (0 before the first save), sends only the fields to
change, and is audited with each changed field before and after. No business logic here.
"""

from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.core.recent_auth import RecentAuth
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import Subject
from app.modules.integrations.service import connector_settings as service
from app.modules.integrations.service.mailboxes import MANAGE
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.ratelimit import rate_limit

router = APIRouter(
    prefix="/integrations/connector-settings",
    tags=["integrations"],
    dependencies=[Depends(rate_limit("integrations"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": f"Missing permission ({MANAGE})."},
    },
)
Manage = Annotated[Subject, Depends(require_permission(MANAGE))]


class ConnectorSettingsIn(BaseModel):
    """The defaults to change; a field left out keeps its value."""

    model_config = ConfigDict(extra="forbid")

    failing_after_runs: int | None = Field(
        default=None, description="Failed runs in a row before a connector is failing (1-20)."
    )
    error_retention_days: int | None = Field(
        default=None, description="Days a connector's errors are kept (7-365)."
    )
    sync_minutes: int | None = Field(
        default=None, description="How often a new directory syncs, in minutes (15-1440)."
    )


class ConnectorSettingsOut(BaseModel):
    """The tenant's connector defaults (Appendix A's until saved)."""

    failing_after_runs: int
    error_retention_days: int
    sync_minutes: int
    version: int = Field(description="Send back as If-Match; 0 before the first save.")


def _out(values: service.ConnectorDefaults) -> ConnectorSettingsOut:
    return ConnectorSettingsOut(
        failing_after_runs=values.failing_after_runs,
        error_retention_days=values.error_retention_days,
        sync_minutes=values.sync_minutes,
        version=values.version,
    )


@router.get("", summary="Connector defaults")
async def get_connector_settings(
    session: TenantSession, subject: Manage, response: Response
) -> ConnectorSettingsOut:
    """When a connector counts as failing, how long errors are kept, how often new ones sync."""
    del subject
    values = await service.get_connector_settings(session)
    set_etag(response, values.version)
    return _out(values)


@router.put("", summary="Save connector defaults", dependencies=[RecentAuth])
async def put_connector_settings(  # noqa: PLR0913, PLR0917 - FastAPI parameters
    body: ConnectorSettingsIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
    note: Annotated[
        AuditNote, audited("connector_settings.changed", object_type="connector_settings")
    ],
) -> ConnectorSettingsOut:
    """Save the fields sent. They apply from the next run, purge or new directory."""
    current = await service.get_connector_settings(session)
    saved, details = await service.save_connector_settings(
        session,
        replace(current, **body.model_dump(exclude_none=True)),
        expected_version=version,
    )
    note.object_id = str(subject.tenant_id)
    note.details = details
    note.skip = not details
    set_etag(response, saved.version)
    return _out(saved)
