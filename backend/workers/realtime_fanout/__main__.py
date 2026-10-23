"""`python -m workers.realtime_fanout` (make worker-fanout): domain events → live screens."""

import asyncio
import sys

from app.core.database import Database
from app.core.logging import get_logger
from app.core.modules import discover_modules
from app.shared.events import EventRegistry, install_registry
from app.shared.events.consumers import validate_consumer
from app.shared.realtime import CentrifugoClient, RealtimeRegistry
from workers import bus, runtime
from workers.consumers.runner import RetryPolicy
from workers.heartbeat import Heartbeat
from workers.metrics import ConsumerMetrics, FanoutMetrics
from workers.realtime_fanout.fanout import Fanout
from workers.realtime_fanout.runner import FanoutRunner, consumer_spec

log = get_logger("workers.realtime_fanout")


def load_registry() -> RealtimeRegistry:
    """Every module's realtime routes, with the event registry installed and checked."""
    modules = discover_modules()
    events = EventRegistry.from_modules(modules)
    install_registry(events)
    registry = RealtimeRegistry.build(modules)
    validate_consumer(consumer_spec(registry), module=None, registry=events)
    return registry


async def main(stop: asyncio.Event) -> None:
    """The fan-out runner + heartbeat until `stop`."""
    settings = runtime.load_settings("supportx-fanout")
    client = CentrifugoClient.from_settings(settings)
    database = Database.from_settings(settings)
    if client is None or database is None:
        log.error("fanout_not_configured", needs="SUPPORTX_CENTRIFUGO_* and SUPPORTX_DATABASE_URL")
        return
    provider, meter = runtime.meter(settings)
    started = asyncio.Event()
    ops = await runtime.start_ops(settings, ready=lambda: started.is_set() and not stop.is_set())
    consumer_metrics = ConsumerMetrics()
    consumer_metrics.bind(meter)
    metrics = FanoutMetrics()
    metrics.bind(meter)
    registry = load_registry()
    connected = await bus.connect(settings, "fanout")
    spec = consumer_spec(registry)
    runner = FanoutRunner(
        registry=registry,
        fanout=Fanout(client, metrics, rate=settings.realtime_tenant_publications_per_second),
        database=database,
        window=settings.realtime_coalesce_ms / 1000,
        js=connected.js,
        names=connected.names,
        retry=RetryPolicy.from_settings(settings, spec),
        ack_wait=settings.consumer_ack_wait_seconds,
        metrics=consumer_metrics,
    )
    await runner.ensure()
    await runner.subscribe()
    log.info("fanout_ready", event_types=list(spec.event_types))
    started.set()

    async def observe() -> None:
        heartbeat = Heartbeat(
            connected.heartbeats,
            "fanout",
            interval=settings.heartbeat_interval_seconds,
            stats=lambda: {**metrics.snapshot(), "lag_messages": consumer_metrics.lag},
        )
        beat = asyncio.create_task(heartbeat.run(stop))
        while not stop.is_set():
            await runner.refresh_lag()
            await runtime.pause(stop, settings.heartbeat_interval_seconds)
        await beat

    try:
        await asyncio.gather(observe(), runner.run(stop))
    finally:
        await connected.close()
        await client.aclose()
        await database.dispose()
        provider.shutdown()
        await runtime.stop_ops(ops)


if __name__ == "__main__":
    sys.exit(runtime.run(main))
