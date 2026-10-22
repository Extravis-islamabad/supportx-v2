"""Dev-only consumer that logs every event it receives (WP-007).

Run `make worker-consumers` in the dev profile and every event appears in that terminal as one
log line. Disabled in production whatever the settings say (Settings.effective_dev_event_logger).
It starts at the end of the stream the first time, so it never replays old history.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.shared.events import ConsumerSpec, EventEnvelope

log = get_logger("events")


async def log_event(event: EventEnvelope, _session: AsyncSession | None) -> None:
    """One line per event: type, tenant, aggregate, actor and the (ID-only) payload."""
    log.info(
        "event_received",
        event_type=event.event_type,
        event_id=str(event.event_id),
        event_tenant=str(event.tenant_id),
        aggregate=f"{event.aggregate_type}:{event.aggregate_id}",
        aggregate_version=event.aggregate_version,
        actor=f"{event.actor.type}:{event.actor.id}",
        payload=event.payload,
    )


def _enabled(settings: Settings) -> bool:
    return settings.effective_dev_event_logger


DEV_EVENT_LOGGER = ConsumerSpec(
    name="system__dev_event_logger",
    event_types=(">",),
    handler=log_event,
    transactional=False,
    deliver_from="new",
    enabled=_enabled,
)
