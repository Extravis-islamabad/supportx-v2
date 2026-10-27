"""Automation on realtime (WP-029): a changed rule, setting or availability reloads open screens.

The message names nothing: the admin tabs and availability switches refetch what they show.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events import EventEnvelope
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, broadcast

CHANGED = "automation.changed"


async def _changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(publications=[Publication(broadcast(envelope.tenant_id), CHANGED)])


ROUTES = [
    RealtimeRoute(("automation.definition.changed", "automation.availability.changed"), _changed)
]
