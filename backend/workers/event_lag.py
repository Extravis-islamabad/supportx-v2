"""How late an event is handled, logged when it is slow (rule c: data on screen updates live).

Each hop that handles events (a consumer, the realtime fan-out) calls `note_lag` with the
envelope it just took. Above SLOW_AFTER_SECONDS it logs `event_lag` with the stage, the
consumer, the event type and ID, and the lag in milliseconds, so a slow notification in the e2e
suite (or in production) shows which hop held it. Never the payload.
"""

from datetime import UTC, datetime

from app.core.logging import get_logger
from app.shared.events import EventEnvelope

log = get_logger(__name__)

SLOW_AFTER_SECONDS = 2.0


def lag_seconds(envelope: EventEnvelope, now: datetime | None = None) -> float:
    """Seconds from the event's occurrence (its business transaction) to now."""
    return ((now or datetime.now(UTC)) - envelope.occurred_at).total_seconds()


def note_lag(
    stage: str, consumer: str, envelope: EventEnvelope, now: datetime | None = None
) -> float:
    """The event's lag; a warning when it is above SLOW_AFTER_SECONDS."""
    lag = lag_seconds(envelope, now)
    if lag > SLOW_AFTER_SECONDS:
        log.warning(
            "event_lag",
            stage=stage,
            consumer=consumer,
            event_type=envelope.event_type,
            event_id=str(envelope.event_id),
            lag_ms=int(lag * 1000),
        )
    return lag
