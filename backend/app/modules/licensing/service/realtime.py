"""licensing on realtime (WP-011): a plan change reaches every screen of the tenant.

The entitlement cache is invalidated here, before the message goes out, so a screen that
refetches on the message never reads the old plan (the cache consumer does the same, but runs
independently of the fan-out).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.licensing.events import EntitlementChanged
from app.modules.licensing.service.cache_consumer import invalidate_with
from app.shared.events import EventEnvelope
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, broadcast


async def _plan_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    await invalidate_with(get_settings(), envelope)
    fields = tuple(envelope.payload.get("changed_fields", ()))
    return RealtimeEffects(
        publications=[
            Publication(broadcast(envelope.tenant_id), "entitlements.changed", fields=fields)
        ]
    )


ROUTES = [RealtimeRoute((EntitlementChanged.event_type,), _plan_changed)]
