"""Tell tenant admins before a sign-in certificate or secret runs out (REQ-SEC-011; WP-057 S2b-2).

Daily, in every tenant: each single sign-on provider's items are checked (domain/expiry.py):
- **SAML:** every signing certificate Keycloak holds for it (up to two, so a rollover's new
  certificate is watched too), read through the identity service account. Without Keycloak the
  last connection check's date stands in for the one certificate it saw;
- **OIDC:** the client secret's expiry an admin entered.

An alert due goes to the outbox (`SignInSecretExpiring`) with its marks in the same transaction
(rule b), so a crash never sends it twice and never loses it; a locked, required notice turns it
into a message to the tenant's admins (service/security_notices.py).
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.identity_access.domain.expiry import certificates, due
from app.modules.identity_access.events import SignInSecretExpiring
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdmin,
    IdentityAdminNotConfigured,
    IdentityAdminUnavailable,
    KeycloakAdmin,
)
from app.modules.identity_access.infra.models import SecurityExpiryMark, SsoProvider
from app.shared.events import record_event
from app.shared.ids import new_id

log = get_logger(__name__)

SECRET_ITEM = "client_secret"  # noqa: S105 - the name of a marked item, not a secret
# The item when no identity service account is set up: the last connection check's date only.
LAST_CHECKED = "last_checked_certificate"

Item = tuple[str, Literal["certificate", "client_secret"], datetime]


async def _certificate_items(provider: SsoProvider, admin: IdentityAdmin | None) -> list[Item]:
    if admin is not None:
        # Keycloak's list only: falling back to the check's date on a passing outage would watch
        # the same certificate under a second name and could alert it twice. Skipped today, then.
        try:
            found = await admin.provider(provider.alias)
        except (IdentityAdminUnavailable, IdentityAdminNotConfigured):
            log.warning("sign_in_expiry_keycloak_unavailable", provider_id=str(provider.id))
            return []
        listed = (found or {}).get("config", {}).get("signingCertificate")
        return [(c.fingerprint, "certificate", c.not_after) for c in certificates(listed)]
    checked = (provider.last_check or {}).get("certificate_not_after")
    if not checked:
        return []
    return [(LAST_CHECKED, "certificate", datetime.fromisoformat(str(checked)))]


async def _items(provider: SsoProvider, admin: IdentityAdmin | None) -> list[Item]:
    items: list[Item] = []
    if provider.protocol == "saml":
        items += await _certificate_items(provider, admin)
    if provider.client_secret_expires_at is not None:
        items.append((SECRET_ITEM, "client_secret", provider.client_secret_expires_at))
    return items


async def check_tenant(
    session: AsyncSession, tenant_id: uuid.UUID, admin: IdentityAdmin | None, now: datetime
) -> int:
    """One tenant's due alerts: marks written and events raised together; how many alerts."""
    sent = 0
    providers = await session.scalars(
        select(SsoProvider).where(SsoProvider.deleted_at.is_(None), SsoProvider.state != "draft")
    )
    for provider in list(providers):
        for key, kind, expires_at in await _items(provider, admin):
            marked = set(
                await session.scalars(
                    select(SecurityExpiryMark.threshold).where(
                        SecurityExpiryMark.provider_id == provider.id,
                        SecurityExpiryMark.item == key,
                    )
                )
            )
            alert, marks = due(expires_at, now, marked)
            if alert is None:
                continue
            await session.execute(
                insert(SecurityExpiryMark)
                .values(
                    [
                        {
                            "tenant_id": tenant_id,
                            "id": new_id(),
                            "provider_id": provider.id,
                            "item": key,
                            "threshold": threshold,
                        }
                        for threshold in sorted(marks)
                    ]
                )
                .on_conflict_do_nothing()
            )
            await record_event(
                session,
                SignInSecretExpiring(
                    provider_id=provider.id, item=kind, days_left=alert, expires_at=expires_at
                ),
                aggregate_id=provider.id,
            )
            sent += 1
    return sent


async def expiry_schedule(database: Database, settings: Settings) -> None:
    """Daily, in every tenant (each in its own session, RLS): the alerts due today."""
    admin = KeycloakAdmin.from_settings(settings)
    now = datetime.now(UTC)
    try:
        async with database.platform_session() as platform:
            tenants = list((await platform.scalars(text("SELECT audit_tenant_ids()"))).all())
        for tenant in tenants:
            async with database.tenant_session(TenantContext(tenant)) as session:
                count = await check_tenant(session, tenant, admin, now)
            if count:
                log.info("sign_in_expiry_alerts", tenant_id=str(tenant), alerts=count)
    finally:
        if admin is not None:
            await admin.close()
