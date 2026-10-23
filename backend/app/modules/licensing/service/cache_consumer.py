"""Consumer that drops a tenant's cached entitlement when it changes (WP-009).

Runs in the consumer worker. Not transactional: its only effect is in Valkey and bumping the
cache generation twice is harmless, so redelivery needs no processed_events record.
"""

from collections.abc import Awaitable, Callable

import valkey.asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.modules.licensing.events import EntitlementChanged
from app.modules.licensing.infra.cache import ValkeyEntitlementCache
from app.shared.events import ConsumerSpec, EventEnvelope

log = get_logger(__name__)

CONSUMER_NAME = "licensing__invalidate_cache"


async def invalidate_with(settings: Settings, envelope: EventEnvelope) -> None:
    """Bump the tenant's cache generation in the Valkey of `settings`."""
    if settings.valkey_url is None:
        return
    client = valkey.asyncio.from_url(settings.valkey_url.get_secret_value())  # type: ignore[no-untyped-call]  # valkey-py ships no annotation for from_url
    try:
        cache = ValkeyEntitlementCache(
            client,
            prefix=settings.valkey_key_prefix,
            ttl_seconds=settings.entitlement_cache_ttl_seconds,
        )
        await cache.invalidate(envelope.tenant_id)
    finally:
        await client.aclose()
    log.info("entitlement_cache_invalidated", tenant_id=str(envelope.tenant_id))


def handler(
    settings: Callable[[], Settings] = get_settings,
) -> Callable[[EventEnvelope, AsyncSession | None], Awaitable[None]]:
    """The consumer handler (settings injectable for tests)."""

    async def handle(envelope: EventEnvelope, session: AsyncSession | None) -> None:
        del session
        await invalidate_with(settings(), envelope)

    return handle


CACHE_INVALIDATION = ConsumerSpec(
    name=CONSUMER_NAME,
    event_types=(EntitlementChanged.event_type,),
    handler=handler(),
    transactional=False,
    enabled=lambda settings: settings.valkey_url is not None,
)
