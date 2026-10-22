"""Process plumbing shared by the worker entry points (settings, logging, signals, metrics)."""

import asyncio
import contextlib
import signal
from collections.abc import Awaitable, Callable

from opentelemetry.metrics import Meter
from opentelemetry.sdk.metrics import MeterProvider

from app.core.config import Settings
from app.core.logging import configure_logging, get_logger
from workers.metrics import METER_NAME, build_meter_provider

log = get_logger(__name__)


def load_settings(service_name: str) -> Settings:
    """Settings from the environment / backend/.env, named after this worker."""
    settings = Settings.load(service_name=service_name)
    configure_logging(settings)
    return settings


def meter(settings: Settings) -> tuple[MeterProvider, Meter]:
    """Meter provider for this process, and the events meter."""
    provider = build_meter_provider(settings)
    return provider, provider.get_meter(METER_NAME)


async def pause(stop: asyncio.Event, seconds: float) -> None:
    """Sleep `seconds`, or less if `stop` is set meanwhile."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), seconds)


def run(main: Callable[[asyncio.Event], Awaitable[None]]) -> int:
    """Run `main(stop)` until it returns; SIGINT/SIGTERM set `stop` for a clean shutdown."""

    async def _runner() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await main(stop)

    asyncio.run(_runner())
    log.info("worker_stopped")
    return 0
