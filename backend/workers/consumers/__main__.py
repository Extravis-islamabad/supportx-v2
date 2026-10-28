"""`python -m workers.consumers` (make worker-consumers): run every enabled module consumer."""

import asyncio
import sys

import nats.errors

from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.modules import discover_modules
from app.modules import licensing
from app.shared.events import ConsumerSpec, EventRegistry, install_registry
from app.shared.events.consumers import consumers_from_modules
from workers import bus, runtime
from workers.bus import watch_bus
from workers.consumers.runner import ConsumerRunner, RetryPolicy
from workers.consumers.schedules import run_schedule, schedules_from_modules
from workers.heartbeat import Heartbeat
from workers.metrics import ConsumerMetrics
from workers.resilience import Connectivity

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
    started = asyncio.Event()
    connectivity = Connectivity(give_up_after=settings.worker_give_up_seconds)
    ops = await runtime.start_ops(
        settings,
        ready=lambda: started.is_set() and not stop.is_set() and connectivity.connected,
    )
    metrics = ConsumerMetrics()
    metrics.bind(meter)
    specs = enabled_consumers(settings)
    database = Database.from_settings(settings)
    # Handlers ask the entitlement interface like the API does (identity_access.subject_for).
    stop_entitlements = await licensing.start_worker_service(settings, database, discover_modules())
    connected = await bus.connect_until_ready(settings, "consumers", connectivity, stop)
    if connected is None:
        await runtime.stop_ops(ops)
        return
    runners = [
        ConsumerRunner(
            spec,
            js=connected.js,
            names=connected.names,
            database=database,
            retry=RetryPolicy.from_settings(settings, spec),
            ack_wait=settings.consumer_ack_wait_seconds,
            metrics=metrics,
            connectivity=connectivity,
        )
        for spec in specs
    ]
    # Each runner creates and binds its durable consumer in run(), retrying while NATS is away.
    log.info("consumers_ready", consumers=[r.name for r in runners])
    started.set()

    async def observe() -> None:
        heartbeat = Heartbeat(
            connected.heartbeats,
            "consumers",
            interval=settings.heartbeat_interval_seconds,
            stats=lambda: {**metrics.snapshot(), **connectivity.snapshot()},
        )
        beat = asyncio.create_task(heartbeat.run(stop))
        while not stop.is_set():
            watch_bus(connected, connectivity)
            for runner in runners:
                await runner.refresh_lag()
            try:
                info = await connected.js.stream_info(connected.names.dlq_stream)
                metrics.dlq_messages = info.state.messages
            except (nats.errors.Error, OSError):
                log.warning("dlq_info_failed")
            await runtime.pause(stop, settings.heartbeat_interval_seconds)
        await beat

    schedules = (
        schedules_from_modules(discover_modules())
        if database is not None and settings.worker_schedules_enabled
        else []
    )
    log.info("schedules_ready", schedules=[spec.name for spec in schedules])
    try:
        await asyncio.gather(
            observe(),
            *(runner.run(stop) for runner in runners),
            *(run_schedule(spec, database, settings, stop) for spec in schedules if database),
        )
    finally:
        await connected.close()
        await stop_entitlements()
        if database is not None:
            await database.dispose()
        provider.shutdown()
        await runtime.stop_ops(ops)


if __name__ == "__main__":
    sys.exit(runtime.run(main))
