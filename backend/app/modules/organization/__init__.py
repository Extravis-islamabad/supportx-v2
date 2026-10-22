"""Organization module (architecture.md §6.1).

Tenants now; sites, departments and business hours arrive with later work packages.

Public interface for other modules: `get_current_tenant`, `TenantView`, `TenantStatus`.
"""

from app.core.modules import ModuleSpec
from app.modules.organization.api.routes import router
from app.modules.organization.domain.tenant import TenantStatus, TenantView
from app.modules.organization.service.tenants import get_current_tenant

module = ModuleSpec(name="organization", routers=[router])

__all__ = ["TenantStatus", "TenantView", "get_current_tenant", "module"]
