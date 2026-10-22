"""Transactional outbox (architecture.md §6.5; CLAUDE.md rule b; WP-007).

A service writes its business change and its event in ONE transaction:

    async with database.tenant_session(context) as session:     # one unit of work
        ticket.assignee_id = assignee
        await record_event(session, TicketAssigned(...), aggregate_id=ticket.id,
                           aggregate_version=ticket.version)
    # commit: both rows exist. Exception: neither does.

`record_event` only INSERTs a row into `outbox_events`; nothing in the API process talks to NATS
(an import-linter contract forbids `nats` in request code). The relay worker
(workers/outbox_relay) publishes committed rows to JetStream afterwards. A trigger on the table
sends `NOTIFY supportx_outbox` so the relay wakes at commit time; PostgreSQL delivers the
notification only if the transaction commits.

The application role may only INSERT here, and only rows of its own tenant (RLS): it cannot read,
change or delete any outbox row, its own tenant's included.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from opentelemetry import propagate
from sqlalchemy import CheckConstraint, Index, Integer, PrimaryKeyConstraint, String, insert, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import SESSION_TENANT_KEY, TenantContextMissingError
from app.core.request_context import current_request_id
from app.core.tenancy import TenantContext
from app.shared.db.models import Base, TenantScoped, Timestamps
from app.shared.events.envelope import Actor, DomainEvent, EventEnvelope
from app.shared.events.registry import active_registry
from app.shared.ids import new_id

OUTBOX_TABLE = "outbox_events"
OUTBOX_CHANNEL = "supportx_outbox"
PROCESSED_TABLE = "processed_events"


class OutboxEvent(TenantScoped, Timestamps, Base):
    """One event waiting for (or already through) the relay. Append-only for the app."""

    __tablename__ = OUTBOX_TABLE

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, sort_order=-100)  # = event_id
    event_type: Mapped[str] = mapped_column(String(200))
    schema_version: Mapped[int] = mapped_column(Integer)
    aggregate_type: Mapped[str] = mapped_column(String(100))
    aggregate_id: Mapped[str] = mapped_column(String(128))
    envelope: Mapped[dict[str, Any]] = mapped_column(JSONB)
    published_at: Mapped[datetime | None]
    publish_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(1000))

    __table_args__ = (
        # The relay's work queue: only unpublished rows, in event-ID (creation) order.
        Index(
            "ix_outbox_events_unpublished",
            "id",
            postgresql_where=text("published_at IS NULL"),
        ),
        # The purge job's range scan.
        Index(
            "ix_outbox_events_published_at",
            "published_at",
            postgresql_where=text("published_at IS NOT NULL"),
        ),
        CheckConstraint("schema_version >= 1", name="schema_version_positive"),
    )


class ProcessedEvent(TenantScoped, Base):
    """Consumer `consumer` has applied event `event_id` (written in the handler's transaction)."""

    __tablename__ = PROCESSED_TABLE

    consumer: Mapped[str] = mapped_column(String(100))
    event_id: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    # tenant_id leads the primary key (CLAUDE.md rule a: first column of every composite index).
    __table_args__ = (PrimaryKeyConstraint("tenant_id", "consumer", "event_id"),)


def _traceparent() -> str | None:
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier.get("traceparent")


async def record_event(  # noqa: PLR0913 - keyword-only envelope fields, most optional
    session: AsyncSession,
    event: DomainEvent,
    *,
    aggregate_id: uuid.UUID | str,
    aggregate_version: int | None = None,
    actor: Actor | None = None,
    causation_id: uuid.UUID | None = None,
    correlation_id: str | None = None,
    occurred_at: datetime | None = None,
) -> EventEnvelope:
    """Add `event` to the outbox inside the session's current transaction.

    The tenant is the session's tenant (RLS rejects any other). The actor defaults to the
    session's user, or the emitting module as a system actor. Raises UnregisteredEventError for an
    event class no module registered, and TenantContextMissingError outside a tenant session.
    """
    active_registry().require(event)
    context = session.info.get(SESSION_TENANT_KEY)
    if not isinstance(context, TenantContext):
        msg = "events can only be recorded in a tenant session (Database.tenant_session)"
        raise TenantContextMissingError(msg)
    event_class = type(event)
    if actor is None:
        actor = (
            Actor.user(context.user_id)
            if context.user_id
            else Actor.system(event_class.event_type.split(".", 1)[0])
        )
    envelope = EventEnvelope(
        event_id=new_id(),
        event_type=event_class.event_type,
        schema_version=event_class.schema_version,
        tenant_id=context.tenant_id,
        actor=actor,
        occurred_at=occurred_at or datetime.now(UTC),
        aggregate_type=event_class.aggregate_type,
        aggregate_id=str(aggregate_id),
        aggregate_version=aggregate_version,
        correlation_id=correlation_id or current_request_id(),
        causation_id=causation_id,
        traceparent=_traceparent(),
        payload=event.model_dump(mode="json"),
    )
    # Core INSERT without RETURNING: the app role has no SELECT on this table.
    await session.execute(
        insert(OutboxEvent).values(
            id=envelope.event_id,
            tenant_id=envelope.tenant_id,
            event_type=envelope.event_type,
            schema_version=envelope.schema_version,
            aggregate_type=envelope.aggregate_type,
            aggregate_id=envelope.aggregate_id,
            envelope=envelope.model_dump(mode="json"),
        )
    )
    return envelope
