"""Organization endpoints."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.modules.audit import audited
from app.modules.organization.domain.tenant import TenantStatus
from app.modules.organization.service import instance
from app.modules.organization.service.tenants import get_current_tenant
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.history import source_of

router = APIRouter(prefix="/organization", tags=["organization"])


class TenantResponse(BaseModel):
    """The caller's tenant. `status` is a code; the UI renders it via labels."""

    id: uuid.UUID
    name: str
    slug: str
    status: TenantStatus


@router.get("/tenant", summary="Current tenant", dependencies=[Depends(require_signed_in())])
async def read_current_tenant(session: TenantSession) -> TenantResponse:
    """Return the tenant of the request (401 `unauthenticated` without a session)."""
    tenant = await get_current_tenant(session)
    return TenantResponse(id=tenant.id, name=tenant.name, slug=tenant.slug, status=tenant.status)


# --- instance settings (WP-042; REQ-ADM-049, 050, 052) --------------------------------------------


class TenantSettingsOut(BaseModel):
    """The tenant's defaults for people and sites, base currency and languages offered."""

    time_zone: str
    week_start: str
    date_format: str
    time_format: str
    country: str | None
    fiscal_year_start_month: int
    contact_email: str | None
    contact_phone: str | None
    base_currency: str
    languages: list[str]
    default_language: str
    version: int


class TenantSettingsPatch(BaseModel):
    """Change the instance settings (If-Match). A set base currency changes only when confirmed."""

    model_config = ConfigDict(extra="forbid")

    time_zone: str | None = Field(default=None, max_length=64)
    week_start: str | None = Field(default=None, max_length=10)
    date_format: str | None = Field(default=None, max_length=12)
    time_format: str | None = Field(default=None, max_length=4)
    country: str | None = Field(default=None, max_length=2)
    fiscal_year_start_month: int | None = None
    contact_email: str | None = Field(default=None, max_length=320)
    contact_phone: str | None = Field(default=None, max_length=40)
    base_currency: str | None = Field(default=None, max_length=3)
    languages: list[str] | None = Field(default=None, max_length=3)
    default_language: str | None = Field(default=None, max_length=5)
    confirm_currency: bool = Field(
        default=False, description="Changing a base currency already set needs this."
    )


def _settings_out(row: Any) -> TenantSettingsOut:  # noqa: ANN401 - the TenantSettings row
    return TenantSettingsOut.model_validate(row, from_attributes=True)


@router.get("/settings", summary="Instance settings")
async def read_settings(
    session: TenantSession,
    response: Response,
    subject: Annotated[Any, Depends(require_signed_in())],  # noqa: ANN401 - identity's Subject
) -> TenantSettingsOut:
    """Read by everyone signed in: the defaults screens use and the languages offered."""
    del subject
    row = await instance.settings_row(session)
    set_etag(response, row.version)
    return _settings_out(row)


@router.patch(
    "/settings",
    summary="Change instance settings",
    responses={409: {"description": "Stale If-Match, or an unconfirmed currency change."}},
    dependencies=[audited("organization.settings_changed", object_type="tenant_settings")],
)
async def patch_settings(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: TenantSettingsPatch,
    version: ExpectedVersion,
    session: TenantSession,
    request: Request,
    response: Response,
    subject: Annotated[Any, Depends(require_signed_in())],  # noqa: ANN401 - identity's Subject
) -> TenantSettingsOut:
    """Needs the organisation's configure right (or settings.manage)."""
    values = body.model_dump(exclude_unset=True, exclude={"confirm_currency"})
    row = await instance.update_settings(
        session,
        subject,
        values,
        expected_version=version,
        confirm_currency=body.confirm_currency,
        source=source_of(request),
    )
    set_etag(response, row.version)
    return _settings_out(row)
