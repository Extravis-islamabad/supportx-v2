"""Integrations events on realtime (WP-011 pattern; docs/architecture/realtime.md).

The mail page and the connector catalogue refetch on tenant-wide signals with no IDs or values;
the API decides who sees what (`integrations.manage_email`, `integrations.view`), so the signals
reveal nothing.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events import EventEnvelope
from app.shared.realtime import Publication, RealtimeEffects, RealtimeRoute, broadcast

MAILBOXES_CHANGED = "integrations.mailboxes_changed"
CONNECTORS_CHANGED = "integrations.connectors_changed"
DIRECTORIES_CHANGED = "integrations.directories_changed"
CONNECTOR_SETTINGS_CHANGED = "integrations.connector_settings_changed"


async def _mailboxes_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    # A mailbox is also a catalogue entry: both pages hear it.
    return RealtimeEffects(
        publications=[
            Publication(broadcast(envelope.tenant_id), MAILBOXES_CHANGED),
            Publication(broadcast(envelope.tenant_id), CONNECTORS_CHANGED),
        ]
    )


async def _connectors_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), CONNECTORS_CHANGED)]
    )


async def _directories_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    # A directory is also a catalogue entry: both pages hear it.
    return RealtimeEffects(
        publications=[
            Publication(broadcast(envelope.tenant_id), DIRECTORIES_CHANGED),
            Publication(broadcast(envelope.tenant_id), CONNECTORS_CHANGED),
        ]
    )


async def _settings_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(
        publications=[Publication(broadcast(envelope.tenant_id), CONNECTOR_SETTINGS_CHANGED)]
    )


ROUTES = [
    RealtimeRoute(("integrations.connector_settings.changed",), _settings_changed),
    RealtimeRoute(("integrations.directory.changed",), _directories_changed),
    RealtimeRoute(("integrations.mailbox.changed",), _mailboxes_changed),
    RealtimeRoute(
        ("integrations.connector.failing", "integrations.connector.recovered"), _connectors_changed
    ),
]
