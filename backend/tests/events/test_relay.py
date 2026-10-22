"""Outbox relay against real PostgreSQL and NATS JetStream (WP-007)."""

import asyncio
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules.system.domain.readiness import FailureReason, ProbeFailedError
from app.modules.system.infra.probes import WorkerHeartbeatProbe
from app.shared.events import BusNames, ConsumerSpec, EventEnvelope, record_event
from tests.db.probe import ProbeItem, ProbeRepository
from tests.events.conftest import (
    RelayFactory,
    RunnerFactory,
    emit,
    outbox_rows,
    run_until,
    stream_message_ids,
    wait_for,
)
from tests.events.sample import ProbeHappened
from tooling import db_testing
from workers import bus
from workers.heartbeat import Heartbeat
from workers.outbox_relay.relay import OutboxRelay

pytestmark = [pytest.mark.db, pytest.mark.nats]


class SimulatedCrash(BaseException):
    """The process dies here (not an Exception: nothing may catch and handle it)."""


class CrashBeforeMark(OutboxRelay):
    """Publishes, gets every JetStream ack, then dies before marking the rows."""

    async def before_mark(self, published: Sequence[Any]) -> None:
        del published
        raise SimulatedCrash


async def unpublished(admin_url: str) -> int:
    return sum(1 for row in await outbox_rows(admin_url) if row["published_at"] is None)


async def test_committed_events_are_published_in_order_and_marked(
    app_db: Database,
    migrated_db: db_testing.ThrowawayDatabase,
    event_bus: bus.Bus,
    make_relay: RelayFactory,
    tenant: uuid.UUID,
) -> None:
    envelopes = await emit(app_db, tenant, count=3)
    relay = make_relay()
    await relay.connect()
    try:
        assert await relay.drain() == 3
    finally:
        await relay.close()

    assert await stream_message_ids(event_bus) == [str(e.event_id) for e in envelopes]
    first = await event_bus.js.get_msg(event_bus.names.events_stream, 1)
    assert first.subject == f"{event_bus.names.events_root}.{tenant}.probe.item.happened"
    assert EventEnvelope.from_json(first.data or b"") == envelopes[0]
    rows = await outbox_rows(migrated_db.admin_url)
    assert all(row["published_at"] is not None for row in rows)
    assert {row["publish_attempts"] for row in rows} == {1}


async def test_rolled_back_change_is_never_published(
    app_db: Database, event_bus: bus.Bus, make_relay: RelayFactory, tenant: uuid.UUID
) -> None:
    async def change_then_fail() -> None:
        async with app_db.tenant_session(TenantContext(tenant)) as session:
            await record_event(session, ProbeHappened(note="never"), aggregate_id="x")
            raise RuntimeError

    with pytest.raises(RuntimeError):
        await change_then_fail()
    relay = make_relay()
    await relay.connect()
    try:
        assert await relay.drain() == 0
    finally:
        await relay.close()
    assert await stream_message_ids(event_bus) == []


async def test_notify_wakes_the_relay_without_waiting_for_the_poll(
    app_db: Database, event_bus: bus.Bus, make_relay: RelayFactory, tenant: uuid.UUID
) -> None:
    relay = make_relay(poll_interval=30.0)  # a poll would take 30 s: only NOTIFY can be this fast
    stop = asyncio.Event()
    task = asyncio.create_task(relay.run(stop))
    try:
        await asyncio.sleep(0.5)  # relay connected, drained the empty outbox, now waiting
        (envelope,) = await emit(app_db, tenant)
        started = asyncio.get_running_loop().time()

        async def arrived() -> bool:
            return await stream_message_ids(event_bus) == [str(envelope.event_id)]

        await wait_for(arrived, within=2.0, interval=0.01)
        assert asyncio.get_running_loop().time() - started < 1.0
    finally:
        stop.set()
        await task


async def test_crash_after_publish_before_mark_is_deduplicated_and_processed_once(
    app_db: Database,
    migrated_db: db_testing.ThrowawayDatabase,
    event_bus: bus.Bus,
    make_relay: RelayFactory,
    make_runner: RunnerFactory,
    tenant: uuid.UUID,
) -> None:
    envelopes = await emit(app_db, tenant, count=5)
    crashing = make_relay(CrashBeforeMark)
    await crashing.connect()
    try:
        with pytest.raises(SimulatedCrash):
            await crashing.publish_batch()
    finally:
        await crashing.close()
    # Published and acknowledged, but the transaction never committed: still "unpublished".
    assert len(await stream_message_ids(event_bus)) == 5
    assert await unpublished(migrated_db.admin_url) == 5

    restarted = make_relay()
    await restarted.connect()
    try:
        assert await restarted.drain() == 5
    finally:
        await restarted.close()
    assert restarted.metrics.duplicates_total == 5  # JetStream recognised every Nats-Msg-Id
    assert await stream_message_ids(event_bus) == [str(e.event_id) for e in envelopes]
    assert await unpublished(migrated_db.admin_url) == 0

    async def apply(event: EventEnvelope, session: AsyncSession | None) -> None:
        assert session is not None
        await ProbeRepository(session).add(ProbeItem(title=str(event.event_id)))

    runner = make_runner(
        ConsumerSpec(name="probe__crash_relay", event_types=("probe.item.happened",), handler=apply)
    )

    async def all_applied() -> bool:
        return runner.metrics.processed.get(runner.name, 0) == 5

    await run_until([runner.run], all_applied)
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        titles = sorted(i.title for i in (await ProbeRepository(session).list(limit=50)).items)
    assert titles == sorted(str(e.event_id) for e in envelopes)
    assert runner.metrics.duplicates.get(runner.name, 0) == 0


async def test_relay_restart_loses_nothing(
    app_db: Database,
    migrated_db: db_testing.ThrowawayDatabase,
    event_bus: bus.Bus,
    make_relay: RelayFactory,
    tenant: uuid.UUID,
) -> None:
    envelopes = [e for _ in range(5) for e in await emit(app_db, tenant, count=100)]
    first = make_relay(batch_size=50)
    await first.connect()
    try:
        await first.publish_batch()
        await first.publish_batch()  # 100 of 500 out, then the process "stops"
    finally:
        await first.close()
    assert await unpublished(migrated_db.admin_url) == 400

    second = make_relay(batch_size=50)
    stop = asyncio.Event()
    task = asyncio.create_task(second.run(stop))
    try:

        async def done() -> bool:
            return await unpublished(migrated_db.admin_url) == 0

        await wait_for(done)
    finally:
        stop.set()
        await task
    assert await stream_message_ids(event_bus) == [str(e.event_id) for e in envelopes]


async def test_two_relays_in_parallel_publish_each_event_exactly_once(
    app_db: Database,
    migrated_db: db_testing.ThrowawayDatabase,
    event_bus: bus.Bus,
    make_relay: RelayFactory,
    tenant: uuid.UUID,
) -> None:
    envelopes = [e for _ in range(20) for e in await emit(app_db, tenant, count=100)]
    relays = [make_relay(batch_size=50), make_relay(batch_size=50)]

    async def done() -> bool:
        return await unpublished(migrated_db.admin_url) == 0

    await run_until([relay.run for relay in relays], done, within=30)

    ids = await stream_message_ids(event_bus)
    assert len(ids) == 2000
    assert set(ids) == {str(e.event_id) for e in envelopes}
    assert sum(r.metrics.duplicates_total for r in relays) == 0  # SKIP LOCKED: no overlap at all
    assert sum(r.metrics.published_total for r in relays) == 2000


async def test_publish_failure_keeps_the_row_and_records_the_error(
    app_db: Database,
    migrated_db: db_testing.ThrowawayDatabase,
    event_bus: bus.Bus,
    make_relay: RelayFactory,
    tenant: uuid.UUID,
) -> None:
    (envelope,) = await emit(app_db, tenant)
    broken = make_relay(names=BusNames("nostream_"), publish_timeout=1.0)  # stream does not exist
    await broken.connect()
    try:
        assert await broken.publish_batch() == (1, 0)
    finally:
        await broken.close()
    (row,) = await outbox_rows(migrated_db.admin_url)
    assert row["published_at"] is None
    assert row["publish_attempts"] == 1
    assert row["last_error"]
    assert broken.metrics.failed_total == 1

    healthy = make_relay()
    await healthy.connect()
    try:
        assert await healthy.drain() == 1
    finally:
        await healthy.close()
    assert await stream_message_ids(event_bus) == [str(envelope.event_id)]
    (row,) = await outbox_rows(migrated_db.admin_url)
    assert row["publish_attempts"] == 2
    assert row["last_error"] is None


async def test_purge_removes_only_old_published_rows(
    app_db: Database,
    migrated_db: db_testing.ThrowawayDatabase,
    make_relay: RelayFactory,
    tenant: uuid.UUID,
) -> None:
    old_published, new_published, old_unpublished = await emit(app_db, tenant, count=3)
    admin = await asyncpg.connect(migrated_db.admin_url)
    try:
        two_days_ago = datetime.now(UTC) - timedelta(days=2)
        await admin.execute(
            "UPDATE outbox_events SET published_at = $2, created_at = $2 WHERE id = $1",
            old_published.event_id,
            two_days_ago,
        )
        await admin.execute(
            "UPDATE outbox_events SET published_at = now() WHERE id = $1", new_published.event_id
        )
        await admin.execute(
            "UPDATE outbox_events SET created_at = $2 WHERE id = $1",
            old_unpublished.event_id,
            two_days_ago,
        )
    finally:
        await admin.close()

    relay = make_relay(retention=timedelta(hours=24))
    await relay.connect()
    try:
        assert await relay.maybe_purge() == 1
        assert await relay.maybe_purge() == 0  # not again within the purge interval
        assert await relay.refresh_backlog_age() > 86400  # the old unpublished row
    finally:
        await relay.close()
    remaining = {row["id"] for row in await outbox_rows(migrated_db.admin_url)}
    assert remaining == {new_published.event_id, old_unpublished.event_id}


async def test_heartbeats_drive_the_readiness_probe(event_bus: bus.Bus, nats_server: str) -> None:
    def probe(kind: str, stale_after_s: float = 20.0) -> WorkerHeartbeatProbe:
        return WorkerHeartbeatProbe(
            nats_server,
            name=kind,
            bucket=event_bus.names.heartbeat_bucket,
            kind=kind,
            stale_after_s=stale_after_s,
        )

    with pytest.raises(ProbeFailedError) as missing:
        await probe("relay").check(2.0)
    assert missing.value.reason is FailureReason.NOT_RUNNING

    heartbeat = Heartbeat(event_bus.heartbeats, "relay", interval=1.0, stats=lambda: {"n": 1})
    await heartbeat.beat()
    await probe("relay").check(2.0)
    with pytest.raises(ProbeFailedError) as other_kind:
        await probe("consumers").check(2.0)
    assert other_kind.value.reason is FailureReason.NOT_RUNNING

    stale = {"at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(), "stats": {}}
    await event_bus.heartbeats.put(heartbeat.key, json.dumps(stale).encode())
    with pytest.raises(ProbeFailedError) as old:
        await probe("relay").check(2.0)
    assert old.value.reason is FailureReason.STALE_HEARTBEAT

    stop = asyncio.Event()
    stop.set()
    await heartbeat.run(stop)  # a stopping worker removes its key at once
    with pytest.raises(ProbeFailedError):
        await probe("relay").check(2.0)


async def test_provisioning_is_idempotent(event_bus: bus.Bus, bus_settings: Any) -> None:  # noqa: ANN401 - Settings fixture
    before = await event_bus.js.stream_info(event_bus.names.events_stream)
    await bus.provision(event_bus.js, event_bus.names, bus_settings)
    after = await event_bus.js.stream_info(event_bus.names.events_stream)
    assert before.config.subjects == after.config.subjects
    assert after.config.duplicate_window == bus_settings.events_duplicate_window_seconds
    assert after.config.max_age == bus_settings.events_stream_max_age_hours * 3600
