"""Domain events and the envelope every event travels in (architecture.md §6.5; WP-007).

A module declares each event as a `DomainEvent` subclass in its `events.py`. The class fields are
the payload; three class variables name it:

    class TicketAssigned(DomainEvent):
        event_type: ClassVar[str] = "work_items.ticket.assigned"   # <module>.<entity>.<action>
        schema_version: ClassVar[int] = 1
        aggregate_type: ClassVar[str] = "ticket"

        ticket_id: uuid.UUID
        assignee_id: uuid.UUID | None

Payloads carry IDs, changed field names and versions, never sensitive data (architecture.md §8.2):
consumers fetch anything else through the owning module's service. Unknown fields are ignored on
parse, so adding an optional field never breaks an older consumer (see docs/architecture/events.md,
"Versioning").
"""

import re
import uuid
from datetime import datetime
from typing import Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
ActorType = Literal["user", "system"]


class DomainEvent(BaseModel):
    """Base class of every event payload."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_type: ClassVar[str]
    schema_version: ClassVar[int] = 1
    aggregate_type: ClassVar[str]


class Actor(BaseModel):
    """Who caused the event: a user (by ID) or a system component (by name)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    type: ActorType
    id: str = Field(max_length=128)

    @classmethod
    def user(cls, user_id: uuid.UUID) -> Self:
        """A signed-in user."""
        return cls(type="user", id=str(user_id))

    @classmethod
    def system(cls, component: str) -> Self:
        """A system component, e.g. `identity_access` or `workflow`."""
        return cls(type="system", id=component)


class EventEnvelope(BaseModel):
    """What is stored in the outbox and published to NATS, byte for byte."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: uuid.UUID = Field(description="UUIDv7; also the NATS message ID (deduplication).")
    event_type: str = Field(pattern=EVENT_TYPE_PATTERN.pattern)
    schema_version: int = Field(ge=1)
    tenant_id: uuid.UUID
    actor: Actor
    occurred_at: datetime
    aggregate_type: str
    aggregate_id: str = Field(max_length=128)
    aggregate_version: int | None = Field(
        default=None, description="Version of the aggregate after the change, if versioned."
    )
    correlation_id: str | None = Field(
        default=None, description="Request ID of the API call (or the causing event's)."
    )
    causation_id: uuid.UUID | None = Field(
        default=None, description="The event that caused this one, when a consumer emits it."
    )
    traceparent: str | None = Field(default=None, description="W3C trace context.")
    payload: dict[str, Any]

    def to_json(self) -> bytes:
        """Wire format (UTF-8 JSON)."""
        return self.model_dump_json().encode()

    @classmethod
    def from_json(cls, data: bytes | str) -> Self:
        """Parse the wire format; raises pydantic.ValidationError when it is not an envelope."""
        return cls.model_validate_json(data)
