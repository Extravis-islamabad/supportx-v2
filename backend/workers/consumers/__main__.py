"""`python -m workers.consumers` (make worker-consumers): run every enabled module consumer."""

import asyncio
import sys

import nats.errors

from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.modules import discover_modules
from app.shared.events import ConsumerSpec, EventRegistry, install_registry
from app.shared.events.consumers import consumers_from_modules
from workers import bus, runtime
from workers.consumers.runner import ConsumerRunner, RetryPolicy
from workers.heartbeat import Heartbeat
from workers.metrics import ConsumerMetrics

log = get_logger("workers.consumers")


def enabled_consumers(settings: Settings) -> list[ConsumerSpec]:
    """Every consumer the modules declare that is enabled for these settings."""
    modules = discover_modules()
    registry = EventRegistry.from_modules(modules)
    install_registry(registry)
    return [spec for spec in consumers_from_modules(modules, registry) if spec.enabled(settings)]


async def main(stop: asyncio.Event) -> None:
    """All runners + heartbeat until `stop`."""
    settings = runtime.load_settings("supportx-consumers")
    provider, meter = runtime.meter(settings)
    metrics = ConsumerMetrics()
    metrics.bind(meter)
    specs = enabled_consumers(settings)
    database = Database.from_settings(settings)
    connected = await bus.connect(settings, "consumers")
    runners = [
        ConsumerRunner(
            spec,
            js=connected.js,
            names=connected.names,
            database=database,
            retry=RetryPolicy.from_settings(settings, spec),
            ack_wait=settings.consumer_ack_wait_seconds,
            metrics=metrics,
        )
        for spec in specs
    ]
    for runner in runners:
        await runner.ensure()
        await runner.subscribe()
    log.info("consumers_ready", consumers=[r.name for r in runners])

    async def observe() -> None:
        heartbeat = Heartbeat(
            connected.heartbeats,
            "consumers",
            interval=settings.heartbeat_interval_seconds,
            stats=metrics.snapshot,
        )
        beat = asyncio.create_task(heartbeat.run(stop))
        while not stop.is_set():
            for runner in runners:
                await runner.refresh_lag()
            try:
                info = await connected.js.stream_info(connected.names.dlq_stream)
                metrics.dlq_messages = info.state.messages
            except (nats.errors.Error, OSError):
                log.warning("dlq_info_failed")
            await runtime.pause(stop, settings.heartbeat_interval_seconds)
        await beat

    try:
        await asyncio.gather(observe(), *(runner.run(stop) for runner in runners))
    finally:
        await connected.close()
        if database is not None:
            await database.dispose()
        provider.shutdown()


if __name__ == "__main__":
    sys.exit(runtime.run(main))
