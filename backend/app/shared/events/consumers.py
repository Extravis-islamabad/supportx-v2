"""Consumer declarations and the idempotency claim (architecture.md §6.5; WP-007).

A module declares its consumers in `ModuleSpec(consumers=[...])`; the consumer worker
(workers/consumers) turns each into a durable JetStream pull consumer and runs it:

    async def _index_ticket(event: EventEnvelope, session: AsyncSession | None) -> None:
        ...

    ConsumerSpec(
        name="search__index_tickets",                 # "<module>__<purpose>", unique
        event_types=("work_items.ticket.created", "work_items.ticket.updated"),
        handler=_index_ticket,
    )

Transactional consumers (the default) get a tenant session for the event's tenant. The worker
first claims the event in `processed_events` and then calls the handler, in the SAME transaction,
so the claim commits exactly when the handler's effects do. A redelivered event finds its claim
and is skipped: at-least-once delivery, exactly-once effect.

Handlers must not call external systems they cannot make idempotent themselves: the database
transaction protects only database effects (docs/architecture/events.md, "Idempotency").
"""

import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.shared.events.envelope import EVENT_TYPE_PATTERN, EventEnvelope
from app.shared.events.outbox import ProcessedEvent
from app.shared.events.registry import EventRegistry

if TYPE_CHECKING:
    from app.core.modules import ModuleSpec

Handler = Callable[[EventEnvelope, AsyncSession | None], Awaitable[None]]
DeliverFrom = Literal["all", "new"]

_CONSUMER_NAME = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_SEGMENT = r"[a-z][a-z0-9_]*"
_WILDCARD = re.compile(rf"^(>|{_SEGMENT}\.>|{_SEGMENT}\.{_SEGMENT}\.>)$")


class ConsumerRegistrationError(RuntimeError):
    """A consumer declaration breaks the rules. Always a programming error."""


def _always(_settings: Settings) -> bool:
    return True


@dataclass(frozen=True)
class ConsumerSpec:
    """One durable consumer of domain events."""

    name: str
    event_types: tuple[str, ...]
    handler: Handler
    # False: no database work, no tenant session, no idempotency record (e.g. logging).
    transactional: bool = True
    # "new": start at the end of the stream when the consumer is first created.
    deliver_from: DeliverFrom = "all"
    enabled: Callable[[Settings], bool] = _always
    max_attempts: int | None = None  # None = SUPPORTX_CONSUMER_MAX_ATTEMPTS
    ack_wait_seconds: float | None = None  # None = SUPPORTX_CONSUMER_ACK_WAIT_SECONDS


def validate_consumer(spec: ConsumerSpec, *, module: str | None, registry: EventRegistry) -> None:
    """Check name and event filters. `module=None` is for worker built-ins and tests."""
    if not _CONSUMER_NAME.fullmatch(spec.name):
        msg = f"consumer name {spec.name!r} must be lowercase snake case"
        raise ConsumerRegistrationError(msg)
    if module is not None and not spec.name.startswith(f"{module}__"):
        msg = f"consumer {spec.name!r} must be named '{module}__<purpose>'"
        raise ConsumerRegistrationError(msg)
    if not spec.event_types:
        msg = f"consumer {spec.name!r} subscribes to nothing"
        raise ConsumerRegistrationError(msg)
    known = registry.event_types()
    for pattern in spec.event_types:
        if _WILDCARD.fullmatch(pattern):
            continue
        if not EVENT_TYPE_PATTERN.fullmatch(pattern) or pattern not in known:
            msg = f"consumer {spec.name!r}: {pattern!r} is not a registered event type"
            raise ConsumerRegistrationError(msg)


def consumers_from_modules(
    modules: Iterable["ModuleSpec"], registry: EventRegistry
) -> list[ConsumerSpec]:
    """Every consumer the modules declare, validated, in module order."""
    found: list[ConsumerSpec] = []
    names: set[str] = set()
    for module in modules:
        for spec in module.consumers:
            if not isinstance(spec, ConsumerSpec):
                msg = f"{module.name}: consumers must be ConsumerSpec instances"
                raise ConsumerRegistrationError(msg)
            validate_consumer(spec, module=module.name, registry=registry)
            if spec.name in names:
                msg = f"consumer {spec.name!r} is declared twice"
                raise ConsumerRegistrationError(msg)
            names.add(spec.name)
            found.append(spec)
    return found


async def claim(session: AsyncSession, consumer: str, envelope: EventEnvelope) -> bool:
    """Record that `consumer` processes this event; False if it already did (skip it).

    A concurrent duplicate blocks on the primary key until the first transaction ends, then
    sees the row: two deliveries can never both apply their effects.
    """
    result = await session.execute(
        insert(ProcessedEvent)
        .values(tenant_id=envelope.tenant_id, consumer=consumer, event_id=envelope.event_id)
        .on_conflict_do_nothing()
    )
    return bool(getattr(result, "rowcount", 0))
