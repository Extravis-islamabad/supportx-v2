"""Password reset (WP-039 session 2; REQ-SEC-006, REQ-SEC-035; D-099).

"Forgot password?" on the sign-in page leads to SupportX's reset page (Keycloak's own reset flow
is off). The person types their email; SupportX answers the same whatever happens (no way to
learn whether an address has an account) and, within the limits, asks Keycloak for its
set-password e-mail in the tenant's brand and the person's language, valid 60 minutes (Appendix
A) and once. The person chooses the new password on Keycloak's page; it never passes through
SupportX (D-099).

Limits (REQ-SEC-035 AC1): 5 requests per address per hour, 20 per network address per hour;
over them nothing is sent. People who sign in only through single sign-on have no password here:
nothing is sent either.

An admin can instead **require a new password at the next sign-in** (`force_reset`): Keycloak's
required action, and the person's sessions end at once, in Keycloak too (a password reset is the
person's, across their tenants).
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import Conflict, NotFound
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdmin,
    IdentityAdminNotConfigured,
    IdentityAdminUnavailable,
)
from app.modules.identity_access.infra.models import User
from app.modules.identity_access.infra.store import SessionStore
from app.modules.organization import email_branding, get_current_tenant

log = get_logger(__name__)

RESET_LIFESPAN = timedelta(minutes=60)
PER_ADDRESS = (5, timedelta(hours=1))
PER_NETWORK = (20, timedelta(hours=1))
SET_PASSWORD = "UPDATE_PASSWORD"  # noqa: S105 - a Keycloak required action's name


@dataclass(frozen=True)
class ResetRequest:
    """What the reset page sent, and from where."""

    email: str
    network: str | None  # the client's IP address (limits)
    tenant_id: uuid.UUID | None  # the tenant of the address used, if a tenant's own


async def _within_limits(store: SessionStore, request: ResetRequest) -> bool:
    limit, window = PER_ADDRESS
    if await store.hit("reset-address", request.email, window) > limit:
        return False
    if request.network is not None:
        limit, window = PER_NETWORK
        if await store.hit("reset-network", request.network, window) > limit:
            return False
    return True


async def request_reset(
    database: Database,
    settings: Settings,
    store: SessionStore,
    admin: IdentityAdmin | None,
    request: ResetRequest,
) -> None:
    """Send the reset e-mail when there is an account with a password and the limits allow."""
    email = request.email.strip().lower()
    if not email or "@" not in email or admin is None:
        return
    if not await _within_limits(store, ResetRequest(email, request.network, request.tenant_id)):
        log.warning("password_reset_limited")
        return
    try:
        account = await admin.find_user(email)
        if account is None or not account.enabled or not account.has_password:
            return
        tenants = await admin.member_tenants(account.id)
    except (IdentityAdminUnavailable, IdentityAdminNotConfigured):
        log.warning("password_reset_identity_unavailable")
        return
    chosen = str(request.tenant_id) if request.tenant_id is not None else None
    tenant = chosen if chosen in tenants else (tenants[0] if tenants else None)
    if tenant is None:
        return
    async with database.tenant_session(TenantContext(uuid.UUID(tenant))) as session:
        person = await session.scalar(
            select(User).where(User.external_subject == account.id, User.status == "active")
        )
        if person is None or not person.can_sign_in:
            return
        locale = person.ui_locale or person.locale
        brand = await email_branding(session, settings, uuid.UUID(tenant), locale)
        name = (await get_current_tenant(session)).name
    await admin.set_attributes(
        account.id,
        {
            "locale": locale,
            "sx_mail_kind": "reset",
            "sx_brand_name": name,
            "sx_brand_logo": brand.logo_url or "",
            "sx_brand_colour": brand.primary_colour,
        },
    )
    await admin.send_actions_email(account.id, [SET_PASSWORD], int(RESET_LIFESPAN.total_seconds()))
    log.info("password_reset_sent", tenant_id=tenant)


async def signed_in_subject(session: AsyncSession, user_id: uuid.UUID) -> str:
    """The person's Keycloak subject; Conflict when they never signed in (no password to reset)."""
    person = await session.get(User, user_id)
    if person is None or person.deleted_at is not None:
        raise NotFound(code="user_not_found")
    if person.external_subject is None:
        raise Conflict(code="password_reset_not_signed_in")
    return person.external_subject


async def force_reset(admin: IdentityAdmin | None, subject: str) -> None:
    """A new password at the next sign-in; every Keycloak session of the person ends now."""
    if admin is None:
        raise IdentityAdminNotConfigured
    await admin.require_actions(subject, [SET_PASSWORD])
    await admin.logout_user(subject)
