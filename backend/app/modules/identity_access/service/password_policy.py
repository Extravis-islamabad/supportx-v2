"""Worker side of the password policy (WP-039 session 2, REQ-SEC-005; identity_settings.py).

On `identity_access.password_policy.changed` the consumers worker writes the tenant's saved
policy into the realm as `supportx-realm`, the only account with manage-realm, whose secret no
API process holds. The policy is read from the settings row, so the newest save always wins
and a late or repeated event writes nothing stale. The result is recorded on the row
(`applied`, or `failed` with a reason code the screen explains) and other admins' screens follow
live; after `failed` the admin applies it again from the screen. Never retried silently: a
realm left on its old policy must be visible.
"""

from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.modules.identity_access.domain.password_policy import to_keycloak
from app.modules.identity_access.events import IdentitySettingsChanged, PasswordPolicyChanged
from app.modules.identity_access.infra.keycloak_admin import (
    IdentityAdminRefused,
    IdentityAdminUnavailable,
    KeycloakAdmin,
    RealmAdmin,
)
from app.modules.identity_access.infra.models import IdentitySettings
from app.modules.identity_access.service.identity_settings import get_identity_settings
from app.shared.events import ConsumerSpec, EventEnvelope, record_event

log = get_logger(__name__)

RealmAdminFactory = Callable[[Settings], RealmAdmin | None]


async def apply(session: AsyncSession, admin: RealmAdmin | None) -> str:
    """Write the saved policy into the realm; the state recorded (`applied` or `failed`)."""
    row = await session.scalar(select(IdentitySettings).with_for_update())
    if row is None or row.password_policy_state != "applying":  # noqa: S105 - a state code
        return "skipped"  # already applied by an earlier event, or never saved
    policy = (await get_identity_settings(session)).password_policy()
    error: str | None = None
    if admin is None:
        error = "password_policy_not_configured"
    else:
        try:
            await admin.set_password_policy(to_keycloak(policy))
        except IdentityAdminUnavailable:
            error = "password_policy_keycloak_unavailable"
        except IdentityAdminRefused as refused:
            # e.g. the breached list file is missing from Keycloak's password-blacklists folder.
            log.warning("password_policy_refused", status=refused.status, reason=refused.message)
            error = "password_policy_refused"
    row.password_policy_state = "failed" if error else "applied"
    row.password_policy_error = error
    await session.flush()
    await record_event(
        session,
        IdentitySettingsChanged(changed_fields=["password_policy_state"]),
        aggregate_id=row.tenant_id,
        aggregate_version=row.version,
    )
    log.info("password_policy_applied", state=row.password_policy_state, error=error)
    return row.password_policy_state


def handler(
    factory: RealmAdminFactory = KeycloakAdmin.realm_from_settings,
    settings: Callable[[], Settings] = get_settings,
) -> Callable[[EventEnvelope, AsyncSession | None], Awaitable[None]]:
    """The consumer handler (the Keycloak client injectable for tests)."""

    async def handle(envelope: EventEnvelope, session: AsyncSession | None) -> None:
        del envelope
        assert session is not None  # noqa: S101 - transactional consumer
        admin = factory(settings())
        try:
            await apply(session, admin)
        finally:
            if admin is not None:
                await admin.close()

    return handle


PASSWORD_POLICY_APPLY = ConsumerSpec(
    name="identity_access__password_policy_apply",
    event_types=(PasswordPolicyChanged.event_type,),
    handler=handler(),
)
