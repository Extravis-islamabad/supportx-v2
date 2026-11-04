"""Assets on realtime (WP-011 pattern; docs/architecture/realtime.md).

The catalogue (product types, products, states, life cycles, settings) is tenant set-up that
every asset screen reads: a change goes to the tenant-wide channel with no IDs, and open screens
refetch through the API, which checks permissions (as knowledge does for its set-up, D-120).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events import EventEnvelope
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, broadcast

CATALOGUE_CHANGED = "assets.catalogue_changed"


async def _catalogue_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), CATALOGUE_CHANGED)]
    )


ROUTES = [RealtimeRoute(("assets.catalogue.changed", "assets.product.changed"), _catalogue_changed)]
