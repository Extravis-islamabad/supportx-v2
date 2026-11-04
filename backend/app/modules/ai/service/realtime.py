"""ai on realtime (WP-037, 038).

- A settings change reaches every screen of the tenant at once: a tenant-wide signal naming the
  changed fields only; screens refetch and hide or show AI features (REQ-AI-027).
- A summary made or gone stale is announced on its record's channel (`t:{tenant}:wi:{id}` for
  work items), whose subscription is already checked by the owning module; the page refetches
  through the API, which checks again. Only the record ID and whether it is stale go out.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.events import AiSettingsChanged, AiSummaryChanged
from app.shared.events import EventEnvelope
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, broadcast, record

# Record types and their record channel kind (architecture.md §8.1).
RECORD_CHANNELS = {"incident": "wi"}


async def _settings_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    fields = tuple(envelope.payload.get("changed_fields", ()))
    return RealtimeEffects(
        publications=[
            Publication(broadcast(envelope.tenant_id), "ai.settings_changed", fields=fields)
        ]
    )


async def _summary_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    kind = RECORD_CHANNELS.get(str(envelope.payload.get("record_type")))
    if kind is None:
        return RealtimeEffects(publications=[])
    record_id = uuid.UUID(str(envelope.payload["record_id"]))
    return RealtimeEffects(
        publications=[
            Publication(
                record(envelope.tenant_id, kind, record_id),
                "ai.summary_changed",
                fields=("stale",) if envelope.payload.get("stale") else ("summary",),
            )
        ]
    )


ROUTES = [
    RealtimeRoute((AiSettingsChanged.event_type,), _settings_changed),
    RealtimeRoute((AiSummaryChanged.event_type,), _summary_changed),
]
