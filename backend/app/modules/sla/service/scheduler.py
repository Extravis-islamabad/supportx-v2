"""The `sla__scheduler` consumer: a save that moved a record's clocks wakes its workflow.

wp-025-plan.md §3.5: nothing in a request talks to Temporal (rule 5b). The save writes its
`sla.*` clock event to the outbox; this consumer signals the record's Temporal workflow, or
starts it. A signal only means "plan again", so a redelivered event is harmless (not
transactional: no database work). Off where Temporal is not configured; the safety net then
fires everything, up to two minutes late (D-115 D5).
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.modules.sla.events import (
    SlaApplied,
    SlaMet,
    SlaPaused,
    SlaRecalculated,
    SlaResumed,
    SlaSetByHand,
    SlaStopped,
)
from app.shared.events import ConsumerSpec, EventEnvelope

log = get_logger(__name__)

# Every event of a save that moves a clock (firing's own events need no wake: it plans itself).
TRIGGERS = tuple(
    e.event_type
    for e in (SlaApplied, SlaPaused, SlaResumed, SlaMet, SlaStopped, SlaRecalculated, SlaSetByHand)
)


class Waker(Protocol):
    """Plans a record's clocks again (Temporal's `TemporalWaker` in production)."""

    async def changed(self, tenant_id: uuid.UUID, record_id: uuid.UUID) -> None:
        """Signal the record's workflow, starting it if it is not running."""
        ...


_wakers: dict[tuple[str, str, str], Waker] = {}


async def _temporal(settings: Settings) -> Waker:
    """One client per address, namespace and queue for the worker's lifetime."""
    from app.modules.sla.infra.temporal import (  # noqa: PLC0415 - the SDK loads only here
        TemporalWaker,
        connect,
    )

    if settings.temporal_address is None:  # pragma: no cover - `enabled` keeps this away
        msg = "SUPPORTX_TEMPORAL_ADDRESS is not set"
        raise RuntimeError(msg)
    key = (settings.temporal_address, settings.temporal_namespace, settings.temporal_task_queue)
    if key not in _wakers:
        client = await connect(settings.temporal_address, settings.temporal_namespace)
        _wakers[key] = TemporalWaker(client, settings.temporal_task_queue)
    return _wakers[key]


def handler(
    waker: Callable[[], Awaitable[Waker]] | None = None,
    settings: Callable[[], Settings] = get_settings,
) -> Callable[[EventEnvelope, AsyncSession | None], Awaitable[None]]:
    """The consumer handler (the waker injectable for tests)."""

    async def handle(envelope: EventEnvelope, session: AsyncSession | None) -> None:
        del session
        found = await (waker() if waker is not None else _temporal(settings()))
        record_id = uuid.UUID(str(envelope.payload["record_id"]))
        await found.changed(envelope.tenant_id, record_id)
        log.debug("sla_woken", tenant_id=str(envelope.tenant_id), record_id=str(record_id))

    return handle


SCHEDULER = ConsumerSpec(
    name="sla__scheduler",
    event_types=TRIGGERS,
    handler=handler(),
    transactional=False,
    enabled=lambda settings: settings.temporal_address is not None,
)
