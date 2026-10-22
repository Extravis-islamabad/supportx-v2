"""Latency and throughput of the outbox → relay → JetStream → consumer path (WP-007).

Measured on whatever stack runs the tests (dev stack locally, service containers in CI) and
printed; set SUPPORTX_PERF_REPORT=<file> to also write them as JSON. The only hard assertion is
the spec target: p95 commit → consumer received under one second.
"""

import asyncio
import json
import os
import statistics
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database
from app.core.tenancy import TenantContext
from app.shared.events import ConsumerSpec, EventEnvelope, record_event
from tests.events.conftest import RelayFactory, RunnerFactory, emit, outbox_rows, wait_for
from tests.events.sample import ProbeHappened
from tooling import db_testing

pytestmark = [pytest.mark.db, pytest.mark.nats]

LATENCY_EVENTS = 1000
THROUGHPUT_EVENTS = 10_000


def report(name: str, values: dict[str, float | int]) -> None:
    line = f"\n[perf] {name}: " + ", ".join(f"{k}={v}" for k, v in values.items())
    print(line)  # noqa: T201 - the numbers are the point of this test
    if target := os.environ.get("SUPPORTX_PERF_REPORT"):
        path = Path(target)
        existing = json.loads(path.read_text()) if path.is_file() else {}
        existing[name] = values
        path.write_text(json.dumps(existing, indent=2))


async def test_commit_to_consumer_latency_for_1000_events(
    app_db: Database,
    make_relay: RelayFactory,
    make_runner: RunnerFactory,
    tenant: uuid.UUID,
    capsys: pytest.CaptureFixture[str],
) -> None:
    committed: dict[uuid.UUID, float] = {}
    received: dict[uuid.UUID, float] = {}

    async def stamp(event: EventEnvelope, _session: AsyncSession | None) -> None:
        received.setdefault(event.event_id, time.perf_counter())

    runner = make_runner(
        ConsumerSpec(
            name="probe__latency",
            event_types=("probe.item.happened",),
            handler=stamp,
            transactional=False,
        )
    )
    relay = make_relay()
    stop = asyncio.Event()
    await runner.ensure()
    await runner.subscribe()
    workers = [asyncio.create_task(relay.run(stop)), asyncio.create_task(runner.run(stop))]
    try:
        await asyncio.sleep(0.5)  # both connected and idle
        for i in range(LATENCY_EVENTS):  # one transaction per event, like 1,000 API calls
            async with app_db.tenant_session(TenantContext(tenant)) as session:
                envelope = await record_event(
                    session, ProbeHappened(note=str(i)), aggregate_id=uuid.uuid4()
                )
            committed[envelope.event_id] = time.perf_counter()

        async def all_received() -> bool:
            return len(received) == LATENCY_EVENTS

        await wait_for(all_received, within=60)
    finally:
        stop.set()
        await asyncio.gather(*workers, return_exceptions=True)

    latencies_ms = sorted((received[k] - committed[k]) * 1000 for k in committed)
    cuts = statistics.quantiles(latencies_ms, n=100, method="inclusive")
    values = {
        "events": LATENCY_EVENTS,
        "p50_ms": round(cuts[49], 1),
        "p95_ms": round(cuts[94], 1),
        "p99_ms": round(cuts[98], 1),
        "max_ms": round(latencies_ms[-1], 1),
    }
    with capsys.disabled():
        report("latency_commit_to_consumer", values)
    assert values["p95_ms"] < 1000, values


async def test_relay_throughput_for_10000_events(
    app_db: Database,
    migrated_db: db_testing.ThrowawayDatabase,
    make_relay: RelayFactory,
    tenant: uuid.UUID,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for _ in range(THROUGHPUT_EVENTS // 1000):
        await emit(app_db, tenant, count=1000)
    relay = make_relay(batch_size=200)  # the default SUPPORTX_RELAY_BATCH_SIZE
    await relay.connect()
    try:
        started = time.perf_counter()
        published = await relay.drain()
        elapsed = time.perf_counter() - started
    finally:
        await relay.close()
    assert published == THROUGHPUT_EVENTS
    assert all(row["published_at"] is not None for row in await outbox_rows(migrated_db.admin_url))
    values = {
        "events": THROUGHPUT_EVENTS,
        "seconds": round(elapsed, 2),
        "events_per_second": round(THROUGHPUT_EVENTS / elapsed),
        "relays": 1,
        "batch_size": 200,
    }
    with capsys.disabled():
        report("relay_throughput", values)
