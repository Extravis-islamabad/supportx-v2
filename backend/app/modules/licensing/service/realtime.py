"""licensing on realtime (WP-011): a plan change reaches every screen of the tenant.

A change to who counts as a technician (someone added, provisioned, switched on or off, or their
type changed) changes the plan's usage: the licence page refetches it (WP-042, REQ-ADM-109). The
signal names nothing; the page reads the count through the entitlement interface. Only the
identity events' type names are used here, never identity_access's code.

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


# Fields of identity_access.user.updated that can change the technician count.
_COUNTED_FIELDS = frozenset({"user_type", "status"})


async def _usage_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    if envelope.event_type.endswith(".updated") and not (
        _COUNTED_FIELDS & set(envelope.payload.get("changed_fields", ()))
    ):
        return RealtimeEffects()
    return RealtimeEffects(
        publications=[
            Publication(broadcast(envelope.tenant_id), "entitlements.usage_changed", coalesce=True)
        ]
    )


ROUTES = [
    RealtimeRoute((EntitlementChanged.event_type,), _plan_changed),
    RealtimeRoute(
        (
            "identity_access.user.created",
            "identity_access.user.provisioned",
            "identity_access.user.status_changed",
            "identity_access.user.updated",
        ),
        _usage_changed,
    ),
]
