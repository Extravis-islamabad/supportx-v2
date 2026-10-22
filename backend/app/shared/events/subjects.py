"""NATS subject, stream and bucket names (WP-007; docs/architecture/events.md, "Subjects").

    events.<tenant_id>.<module>.<entity>.<action>      every domain event (stream SUPPORTX_EVENTS)
    replay.<consumer>.<tenant_id>.<module>.<entity>.<action>
                                                       a dead letter replayed to ONE consumer
    dlq.<consumer>.<tenant_id>.<module>.<entity>.<action>
                                                       dead letters (stream SUPPORTX_DLQ)

The tenant comes first after the root so one wildcard selects a whole tenant
(`events.<tenant_id>.>`): the realtime fan-out (WP-011) and per-tenant tooling filter on it
without parsing payloads, and NATS account/permission rules can be written per tenant later. The
event type follows as three tokens so consumers filter by module (`events.*.work_items.>`) or by
exact event (`events.*.work_items.ticket.assigned`).

`namespace` prefixes every name. It is empty in real deployments; tests use a random one so
they never touch, and cannot collide with, the streams of a running dev stack.
"""

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class BusNames:
    """Every JetStream name the event bus uses, for one namespace."""

    namespace: str = ""

    def _p(self, name: str) -> str:
        return f"{self.namespace}{name}"

    @property
    def events_stream(self) -> str:
        """Stream holding every domain event (and per-consumer replays)."""
        return self._p("SUPPORTX_EVENTS").upper()

    @property
    def dlq_stream(self) -> str:
        """Stream holding dead letters."""
        return self._p("SUPPORTX_DLQ").upper()

    @property
    def heartbeat_bucket(self) -> str:
        """Key-value bucket where the relay and consumer workers report they are alive."""
        return self._p("SUPPORTX_HEARTBEATS").upper()

    @property
    def events_root(self) -> str:
        """First token of every event subject."""
        return self._p("events")

    @property
    def replay_root(self) -> str:
        """First token of replay subjects."""
        return self._p("replay")

    @property
    def dlq_root(self) -> str:
        """First token of dead-letter subjects."""
        return self._p("dlq")

    def event_subject(self, tenant_id: uuid.UUID, event_type: str) -> str:
        """`events.<tenant>.<module>.<entity>.<action>`."""
        return f"{self.events_root}.{tenant_id}.{event_type}"

    def event_filter(self, pattern: str) -> str:
        """Filter subject for an event type pattern (`>` = all events, any tenant)."""
        if pattern == ">":
            return f"{self.events_root}.>"
        return f"{self.events_root}.*.{pattern}"

    def replay_subject(self, consumer: str, tenant_id: uuid.UUID | str, event_type: str) -> str:
        """Subject that only `consumer` receives."""
        return f"{self.replay_root}.{consumer}.{tenant_id}.{event_type}"

    def replay_filter(self, consumer: str) -> str:
        """Filter subject for replays addressed to `consumer`."""
        return f"{self.replay_root}.{consumer}.>"

    def dlq_subject(self, consumer: str, tenant_id: uuid.UUID | str, event_type: str) -> str:
        """Where `consumer` parks a message it gave up on."""
        return f"{self.dlq_root}.{consumer}.{tenant_id}.{event_type}"
