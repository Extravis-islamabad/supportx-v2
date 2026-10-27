"""Which tenant an address belongs to (WP-017, REQ-SEC-004, D-027).

Before anyone signs in there is no tenant in the transaction, so the lookup goes through two
SECURITY DEFINER functions (migration 0022) that answer one exact question each and return only an
active tenant's id and slug. The answer is a hint (the brand to show, the organization to sign in
to); it never grants access: the session's tenant still comes from the person's own memberships.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    import uuid

    from app.core.database import Database

_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")
_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


@dataclass(frozen=True)
class HostTenant:
    """The tenant an address points to."""

    tenant_id: uuid.UUID
    slug: str


def normalise_host(value: str | None) -> str | None:
    """`Acme.Example.com:443` → `acme.example.com`; None for anything that is not a host name."""
    if not value:
        return None
    host = value.strip().lower().rstrip(".")
    if host.startswith("["):  # an IPv6 literal never names a tenant
        return None
    host = host.split(":", 1)[0]
    return host if len(host) <= 253 and _HOST.fullmatch(host) else None  # noqa: PLR2004 - DNS limit


def subdomain_slug(host: str, base_domain: str | None) -> str | None:
    """`acme` for `acme.<base_domain>` (one label only), else None."""
    if not base_domain:
        return None
    suffix = "." + base_domain.lower().strip(".")
    if not host.endswith(suffix):
        return None
    label = host[: -len(suffix)]
    return label if _LABEL.fullmatch(label) else None


async def tenant_for_host(
    database: Database, host: str | None, base_domain: str | None
) -> HostTenant | None:
    """The active tenant whose subdomain or verified custom domain `host` is, else None."""
    name = normalise_host(host)
    if name is None:
        return None
    slug = subdomain_slug(name, base_domain)
    async with database.platform_session() as session:
        if slug is not None:
            row = (
                await session.execute(
                    text("SELECT tenant_id, slug FROM sx_tenant_for_slug(:slug)"), {"slug": slug}
                )
            ).first()
        else:
            row = (
                await session.execute(
                    text("SELECT tenant_id, slug FROM sx_tenant_for_host(:host)"), {"host": name}
                )
            ).first()
    return HostTenant(row.tenant_id, row.slug) if row is not None else None
