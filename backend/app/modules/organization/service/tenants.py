"""Tenant use cases."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import NotFound
from app.core.tenancy import TenantContext
from app.modules.organization.domain.tenant import TenantStatus, TenantView
from app.modules.organization.events import TenantProvisioned
from app.modules.organization.infra.models import Tenant
from app.shared.events import record_event


async def get_current_tenant(session: AsyncSession) -> TenantView:
    """The tenant of the session. RLS lets supportx_app see only this one row anyway."""
    context = session.info.get(SESSION_TENANT_KEY)
    if not isinstance(context, TenantContext):
        msg = "get_current_tenant needs a tenant session"
        raise TypeError(msg)
    tenant = await session.scalar(select(Tenant).where(Tenant.id == context.tenant_id))
    if tenant is None:
        raise NotFound(code="tenant_not_found")
    return TenantView(
        id=tenant.id, name=tenant.name, slug=tenant.slug, status=TenantStatus(tenant.status)
    )


async def record_tenant_provisioned(session: AsyncSession) -> None:
    """Announce that the session's tenant is ready (outbox, in the caller's transaction).

    Called by whatever creates the tenant, once, after everything it needs exists (D-138).
    """
    context = session.info.get(SESSION_TENANT_KEY)
    if not isinstance(context, TenantContext):
        msg = "record_tenant_provisioned needs a tenant session"
        raise TypeError(msg)
    await record_event(
        session,
        TenantProvisioned(tenant_id=context.tenant_id),
        aggregate_id=context.tenant_id,
        aggregate_version=1,
    )
