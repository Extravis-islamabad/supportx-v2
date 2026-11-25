"""A request's workflow began waiting: one event per wait (WP-047a S5 follow-up; REQ-SR-053 AC1).

Consumes automation's `workflow_instance.changed`. Its `waits_started` lists the nodes whose wait
began in that save, from the save's own steps (lane B's condition 1: a re-save, a retry or an
unrelated edit while waiting lists nothing; a loop back starts it again). For a service request
each started wait raises its own `ServiceRequestWorkflowWaiting` through the outbox, so the
notification engine, idempotent per event, tells the technician or the group once per wait. A
redelivered instance event is skipped by the consumer's processed-events guard.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import automation
from app.modules.work_items.domain.types import SERVICE_REQUEST
from app.modules.work_items.events import ServiceRequestWorkflowWaiting
from app.modules.work_items.infra.models import WorkItem
from app.shared.events import ConsumerSpec, EventEnvelope, record_event

INSTANCE_CHANGED = "automation.workflow_instance.changed"


async def on_instance_changed(envelope: EventEnvelope, session: AsyncSession | None) -> None:
    """Raise one waiting event per wait a request's workflow began in this save."""
    payload = envelope.payload
    started = [str(n) for n in payload.get("waits_started") or []]
    if session is None or not started or payload.get("record_type") != SERVICE_REQUEST.code.value:
        return
    record = await session.get(WorkItem, uuid.UUID(str(payload["record_id"])))
    if record is None or record.deleted_at is not None:
        return
    instance_id = uuid.UUID(str(payload["instance_id"]))
    for node in started:
        kind = await automation.wait_kind(session, instance_id, node)
        if kind is None:
            continue
        await record_event(
            session,
            ServiceRequestWorkflowWaiting(
                work_item_id=record.id, instance_id=instance_id, node_id=node, wait_kind=kind
            ),
            aggregate_id=record.id,
            aggregate_version=record.version,
        )


WORKFLOW_WAITS = ConsumerSpec(
    name="work_items__workflow_waits",
    event_types=(INSTANCE_CHANGED,),
    handler=on_instance_changed,
)

__all__ = ["WORKFLOW_WAITS", "on_instance_changed"]
