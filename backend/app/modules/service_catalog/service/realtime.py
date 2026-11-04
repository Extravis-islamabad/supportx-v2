"""Catalog changes on realtime (WP-030 s1): open catalog screens refetch (no content, §8.2)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events import EventEnvelope
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, broadcast

CHANGED = "service_catalog.changed"


async def _changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """An item or category changed: everyone's catalog screens refetch through the API."""
    del session
    return RealtimeEffects(
        publications=[
            Publication(broadcast(envelope.tenant_id), CHANGED, ids=(str(envelope.aggregate_id),))
        ]
    )


ROUTES = [
    RealtimeRoute(("service_catalog.item.changed", "service_catalog.category.changed"), _changed)
]

__all__ = ["CHANGED", "ROUTES"]
