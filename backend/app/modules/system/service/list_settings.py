"""The shared list-settings store on realtime (WP-049b s4a; rule 5c).

A person's settings or saved views of a list changed: their other windows refetch them. The
message goes to their personal channel only, with the list and view keys (no names, no filters).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events import EventEnvelope
from app.shared.list_settings.events import ListSettingsChanged
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, personal

LIST_SETTINGS_CHANGED = "system.list_settings_changed"


async def _changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    payload = envelope.payload
    actor = envelope.actor.id if envelope.actor.type == "user" else None
    return RealtimeEffects(
        publications=[
            Publication(
                personal(envelope.tenant_id, uuid.UUID(str(payload["user_id"]))),
                LIST_SETTINGS_CHANGED,
                ids=(str(payload["list_key"]), str(payload["view_key"])),
                actor_id=actor,
            )
        ]
    )


REALTIME = [RealtimeRoute((ListSettingsChanged.event_type,), _changed)]
