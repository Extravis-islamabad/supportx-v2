"""Domain events: envelope, registry, transactional outbox, consumer declarations (WP-007).

See docs/architecture/events.md for how an event travels and how to add events and consumers.
"""

from app.shared.events.consumers import ConsumerSpec, Handler, claim
from app.shared.events.envelope import Actor, DomainEvent, EventEnvelope
from app.shared.events.outbox import (
    OUTBOX_CHANNEL,
    OutboxEvent,
    ProcessedEvent,
    caused_by,
    record_event,
)
from app.shared.events.registry import (
    EventRegistry,
    UnregisteredEventError,
    active_registry,
    install_registry,
)
from app.shared.events.subjects import BusNames

__all__ = [
    "OUTBOX_CHANNEL",
    "Actor",
    "BusNames",
    "ConsumerSpec",
    "DomainEvent",
    "EventEnvelope",
    "EventRegistry",
    "Handler",
    "OutboxEvent",
    "ProcessedEvent",
    "UnregisteredEventError",
    "active_registry",
    "caused_by",
    "claim",
    "install_registry",
    "record_event",
]
