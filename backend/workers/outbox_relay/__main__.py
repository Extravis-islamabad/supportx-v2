"""`python -m workers.outbox_relay` (make worker-relay): run one outbox relay until stopped."""

import asyncio
import sys
from datetime import timedelta

from app.core.config import Settings
from app.core.logging import get_logger
from workers import bus, runtime
from workers.heartbeat import Heartbeat
from workers.metrics import RelayMetrics
from workers.outbox_relay.relay import OutboxRelay

log = get_logger("workers.outbox_relay")


def build_relay(settings: Settings, connected: bus.Bus, metrics: RelayMetrics) -> OutboxRelay:
    """A relay configured from settings."""
    if settings.relay_database_url is None:
        msg = "SUPPORTX_RELAY_DATABASE_URL is not set (make backend-env)"
        raise RuntimeError(msg)
    return OutboxRelay(
        dsn=settings.relay_database_url.get_secret_value(),
        js=connected.js,
        names=connected.names,
        batch_size=settings.relay_batch_size,
        poll_interval=settings.relay_poll_interval_seconds,
        publish_timeout=settings.relay_publish_timeout_seconds,
        retention=timedelta(hours=settings.outbox_retention_hours),
        purge_interval=settings.outbox_purge_interval_seconds,
        processed_retention=timedelta(days=settings.processed_events_retention_days),
        metrics=metrics,
    )


async def main(stop: asyncio.Event) -> None:
    """Relay + heartbeat until `stop`."""
    settings = runtime.load_settings("supportx-outbox-relay")
    provider, meter = runtime.meter(settings)
    started = asyncio.Event()
    ops = await runtime.start_ops(settings, ready=lambda: started.is_set() and not stop.is_set())
    metrics = RelayMetrics()
    metrics.bind(meter)
    connected = await bus.connect(settings, "outbox-relay")
    relay = build_relay(settings, connected, metrics)
    started.set()

    def stats() -> dict[str, float | int]:
        return metrics.snapshot()

    async def heartbeat_loop() -> None:
        heartbeat = Heartbeat(
            connected.heartbeats, "relay", interval=settings.heartbeat_interval_seconds, stats=stats
        )
        beat = asyncio.create_task(heartbeat.run(stop))
        while not stop.is_set():
            await relay.refresh_backlog_age()
            await runtime.pause(stop, settings.heartbeat_interval_seconds)
        await beat

    try:
        await asyncio.gather(relay.run(stop), heartbeat_loop())
    finally:
        await connected.close()
        provider.shutdown()
        await runtime.stop_ops(ops)


if __name__ == "__main__":
    sys.exit(runtime.run(main))
