"""Custom fields on realtime (WP-026): any change tells every open screen to reload them.

The message names nothing: forms, lists and records refetch the definitions they show.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events import EventEnvelope
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, broadcast

CHANGED = "metadata.custom_fields_changed"


async def _changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(publications=[Publication(broadcast(envelope.tenant_id), CHANGED)])


ROUTES = [RealtimeRoute(("metadata.custom_field.changed",), _changed)]
