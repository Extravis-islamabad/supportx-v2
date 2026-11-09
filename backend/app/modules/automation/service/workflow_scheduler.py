"""The `automation__workflow_scheduler` consumer: an instance that moved on wakes its waker.

Nothing in a request talks to Temporal (rule b). An instance's change writes
`automation.workflow_instance.changed` to the outbox; this consumer signals the instance's
Temporal workflow, or starts it, while it still runs (waiting or running). A signal only means
"plan again", so a redelivered event is harmless (not transactional: no database work). Off where
Temporal is not configured; the minute sweep then wakes due timers (ADR-043 §5).
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.modules.automation.events import WorkflowInstanceChanged
from app.shared.events import ConsumerSpec, EventEnvelope

log = get_logger(__name__)
_LIVE = {"running", "waiting"}


class InstanceWaker(Protocol):
    """Plans an instance's next wake again (`TemporalInstanceWaker` in production)."""

    async def changed(self, tenant_id: uuid.UUID, instance_id: uuid.UUID) -> None:
        """Signal the instance's workflow, starting it if it is not running."""
        ...


_wakers: dict[tuple[str, str, str], InstanceWaker] = {}


async def _temporal(settings: Settings) -> InstanceWaker:
    """One client per address, namespace and queue for the worker's lifetime."""
    from app.modules.automation.infra.temporal import (  # noqa: PLC0415 - the SDK loads only here
        TemporalInstanceWaker,
        connect,
    )

    if settings.temporal_address is None:  # pragma: no cover - `enabled` keeps this away
        msg = "SUPPORTX_TEMPORAL_ADDRESS is not set"
        raise RuntimeError(msg)
    queue = settings.temporal_workflow_task_queue
    key = (settings.temporal_address, settings.temporal_namespace, queue)
    if key not in _wakers:
        client = await connect(settings.temporal_address, settings.temporal_namespace)
        _wakers[key] = TemporalInstanceWaker(client, queue)
    return _wakers[key]


def handler(
    waker: Callable[[], Awaitable[InstanceWaker]] | None = None,
    settings: Callable[[], Settings] = get_settings,
) -> Callable[[EventEnvelope, AsyncSession | None], Awaitable[None]]:
    """The consumer handler (the waker injectable for tests)."""

    async def handle(envelope: EventEnvelope, session: AsyncSession | None) -> None:
        del session
        if envelope.payload.get("status") not in _LIVE:
            return  # ended or failed: nothing to wake (a retry or restart starts it again)
        found = await (waker() if waker is not None else _temporal(settings()))
        instance_id = uuid.UUID(str(envelope.payload["instance_id"]))
        await found.changed(envelope.tenant_id, instance_id)
        log.debug("workflow_waker_signalled", instance_id=str(instance_id))

    return handle


SCHEDULER = ConsumerSpec(
    name="automation__workflow_scheduler",
    event_types=(WorkflowInstanceChanged.event_type,),
    handler=handler(),
    transactional=False,
    enabled=lambda settings: settings.temporal_address is not None,
)
