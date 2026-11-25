"""Monitoring events on realtime (WP-011 pattern; docs/architecture/realtime.md).

- Health: the CI's own record channel and list audiences (cmdb's, so cmdb's permission checks
  decide who hears it) with `fields=["health"]` and nothing else: the client refetches
  `/monitoring/health`, which applies visibility (the coordinator's S6 condition 4).
- Connections and topology runs: a tenant-wide signal with no IDs; the settings page refetches
  under `monitoring.manage`.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import cmdb
from app.shared.events import EventEnvelope
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, broadcast

HEALTH_FIELD = "health"
CONNECTIONS_CHANGED = "monitoring.connections_changed"


async def _health_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    ci_id = uuid.UUID(str(envelope.payload["ci_id"]))
    publications = await cmdb.ci_field_publications(
        session, envelope.tenant_id, ci_id, (HEALTH_FIELD,)
    )
    return RealtimeEffects(publications=publications)


async def _connections_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), CONNECTIONS_CHANGED)]
    )


ROUTES = [
    RealtimeRoute(("monitoring_integrations.health.changed",), _health_changed),
    RealtimeRoute(
        (
            "monitoring_integrations.connection.changed",
            "monitoring_integrations.topology_run.changed",
        ),
        _connections_changed,
    ),
]
