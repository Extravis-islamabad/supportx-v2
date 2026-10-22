"""Organization endpoints."""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.database import TenantSession
from app.modules.organization.domain.tenant import TenantStatus
from app.modules.organization.service.tenants import get_current_tenant

router = APIRouter(prefix="/organization", tags=["organization"])


class TenantResponse(BaseModel):
    """The caller's tenant. `status` is a code; the UI renders it via labels."""

    id: uuid.UUID
    name: str
    slug: str
    status: TenantStatus


@router.get("/tenant", summary="Current tenant")
async def read_current_tenant(session: TenantSession) -> TenantResponse:
    """Return the tenant of the request (401 `tenant_required` when none is established)."""
    tenant = await get_current_tenant(session)
    return TenantResponse(id=tenant.id, name=tenant.name, slug=tenant.slug, status=tenant.status)
