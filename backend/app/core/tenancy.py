"""Request-scoped tenant context (architecture.md §7.2; CLAUDE.md rule a; WP-005).

The tenant of a request is resolved once, kept in a `TenantContext`, bound into every log line,
and written into each database transaction as `app.tenant_id` (see app/core/database.py), where
PostgreSQL row-level security enforces it.

Resolution today:
- dev and test profiles: the `X-Tenant-ID` header, so the API can be exercised before login exists;
- production: the header is ignored completely. Until WP-006 resolves the tenant from the login
  session, every tenant-scoped endpoint answers 401 `tenant_required` in production.
"""

import uuid
from dataclasses import dataclass

import structlog
from fastapi import Request

from app.core.config import Settings
from app.core.errors import BadRequest, Unauthenticated

TENANT_HEADER = "X-Tenant-ID"
# Profiles in which the header is trusted. Never add "production" here: the header is a
# client-controlled value, and trusting it would let anyone pick any tenant.
HEADER_TRUSTED_PROFILES = frozenset({"dev", "test"})


@dataclass(frozen=True)
class TenantContext:
    """Who the current work is for: the tenant and, once WP-006 lands, the acting user."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID | None = None


class TenantRequired(Unauthenticated):
    """No tenant could be established for this request."""

    code = "tenant_required"


def tenant_from_header(settings: Settings, header_value: str | None) -> TenantContext | None:
    """Tenant from X-Tenant-ID, only in dev/test. Production always returns None."""
    if settings.profile not in HEADER_TRUSTED_PROFILES or header_value is None:
        return None
    try:
        return TenantContext(tenant_id=uuid.UUID(header_value.strip()))
    except ValueError as exc:
        raise BadRequest(code="invalid_tenant_id") from exc


async def resolve_tenant(request: Request) -> TenantContext:
    """FastAPI dependency: the tenant of this request, or 401 `tenant_required`."""
    settings: Settings = request.app.state.settings
    context = tenant_from_header(settings, request.headers.get(TENANT_HEADER))
    if context is None:
        raise TenantRequired
    structlog.contextvars.bind_contextvars(tenant_id=str(context.tenant_id))
    return context
