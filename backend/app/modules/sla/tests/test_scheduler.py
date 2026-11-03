"""The `sla__scheduler` consumer wakes the record's workflow, and only where Temporal runs."""

import uuid
from datetime import UTC, datetime

from app.core.config import Settings
from app.modules.sla.events import SlaBreached, SlaPaused
from app.modules.sla.service.scheduler import SCHEDULER, TRIGGERS, Waker, handler
from app.shared.events import Actor, EventEnvelope


class FakeWaker:
    def __init__(self) -> None:
        self.woken: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def changed(self, tenant_id: uuid.UUID, record_id: uuid.UUID) -> None:
        self.woken.append((tenant_id, record_id))


def _event(event_type: str, record_id: uuid.UUID) -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid.uuid4(),
        event_type=event_type,
        schema_version=1,
        tenant_id=uuid.uuid4(),
        occurred_at=datetime.now(UTC),
        actor=Actor.system("sla"),
        aggregate_type="sla_record",
        aggregate_id=str(record_id),
        payload={"record_type": "incident", "record_id": str(record_id), "kind": "resolution"},
    )


async def test_a_clock_change_signals_the_records_workflow() -> None:
    fake = FakeWaker()

    async def waker() -> Waker:
        return fake

    record = uuid.uuid4()
    event = _event(SlaPaused.event_type, record)
    await handler(waker)(event, None)
    await handler(waker)(event, None)  # redelivered: one more "plan again", harmless
    assert fake.woken == [(event.tenant_id, record)] * 2


def test_firings_own_events_need_no_wake_and_it_is_off_without_temporal() -> None:
    assert SlaPaused.event_type in TRIGGERS
    assert SlaBreached.event_type not in TRIGGERS  # the workflow fired it: it plans itself
    assert not SCHEDULER.enabled(Settings(temporal_address=None))
    assert SCHEDULER.enabled(Settings(temporal_address="temporal:7233"))
    assert not SCHEDULER.transactional
