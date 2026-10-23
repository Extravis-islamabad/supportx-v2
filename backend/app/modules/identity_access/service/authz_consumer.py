"""Consumer that refreshes compiled permissions after access-relevant changes (WP-016).

Any role, assignment, membership, user or entitlement change in a tenant bumps that tenant's
authorization cache generation, so every API process recompiles on its next request. The API
process that made a change already bumped it right after its commit; this covers all the others.
Not transactional: bumping twice is harmless.
"""

from collections.abc import Awaitable, Callable

import valkey.asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.modules.identity_access.service.policy import ValkeySubjectCache
from app.shared.events import ConsumerSpec, EventEnvelope

log = get_logger(__name__)

TRIGGERS = (
    "identity_access.role.changed",
    "identity_access.user_role.changed",
    "identity_access.user.updated",
    "organization.membership.changed",
    "licensing.entitlement.changed",
)


def handler(
    settings: Callable[[], Settings] = get_settings,
) -> Callable[[EventEnvelope, AsyncSession | None], Awaitable[None]]:
    """The consumer handler (settings injectable for tests)."""

    async def handle(envelope: EventEnvelope, session: AsyncSession | None) -> None:
        del session
        current = settings()
        if current.valkey_url is None:
            return
        client = valkey.asyncio.from_url(current.valkey_url.get_secret_value())  # type: ignore[no-untyped-call]  # valkey-py ships no annotation for from_url
        try:
            cache = ValkeySubjectCache(client, prefix=current.valkey_key_prefix, ttl_seconds=1)
            await cache.invalidate(envelope.tenant_id)
        finally:
            await client.aclose()
        log.info(
            "authz_cache_invalidated", tenant_id=str(envelope.tenant_id), cause=envelope.event_type
        )

    return handle


AUTHZ_INVALIDATION = ConsumerSpec(
    name="identity_access__invalidate_authz",
    event_types=TRIGGERS,
    handler=handler(),
    transactional=False,
    enabled=lambda settings: settings.valkey_url is not None,
)
