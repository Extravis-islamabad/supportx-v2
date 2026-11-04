"""ai on realtime (WP-037): a settings change reaches every screen of the tenant at once.

A tenant-wide signal naming the changed fields only; screens refetch the settings and hide or
show AI features (REQ-AI-027: switching off takes effect live for every user).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.events import AiSettingsChanged
from app.shared.events import EventEnvelope
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, broadcast


async def _settings_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    fields = tuple(envelope.payload.get("changed_fields", ()))
    return RealtimeEffects(
        publications=[
            Publication(broadcast(envelope.tenant_id), "ai.settings_changed", fields=fields)
        ]
    )


ROUTES = [RealtimeRoute((AiSettingsChanged.event_type,), _settings_changed)]
