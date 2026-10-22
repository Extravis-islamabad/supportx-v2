"""NATS JetStream setup as code (WP-007; docs/architecture/events.md, "Streams").

Every worker calls `provision()` at startup. It creates the streams and the heartbeat bucket if
they are missing and updates them to the configuration below if they exist, so the bus never
depends on someone running `nats stream add` by hand, and a changed setting (retention,
duplicate window) reaches the server on the next restart.

    SUPPORTX_EVENTS      events.>, replay.>   limits retention, file storage, max age from
                                              settings, duplicate window = dedupe of event IDs
    SUPPORTX_DLQ         dlq.>                dead letters, kept longer for investigation
    SUPPORTX_HEARTBEATS  (KV bucket)          relay/consumer liveness for /ready, TTL'd keys

This module (with the relay) is the only place that publishes to NATS. The API process cannot:
an import-linter contract forbids `nats` in app code apart from the read-only readiness probes.
"""

import contextlib
import math
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import nats
import nats.errors
from nats.aio.client import Client as NatsClient
from nats.js import JetStreamContext, api
from nats.js.errors import BucketNotFoundError, NotFoundError
from nats.js.kv import KeyValue

from app.core.config import Settings
from app.core.logging import get_logger
from app.shared.events import BusNames

log = get_logger(__name__)

# Heartbeat keys outlive a few missed beats, then vanish on their own.
HEARTBEAT_KEY_TTL_SECONDS = 60.0


def bus_names(settings: Settings) -> BusNames:
    """Names for this process's namespace."""
    return BusNames(settings.events_namespace)


def events_stream_config(names: BusNames, settings: Settings) -> api.StreamConfig:
    """The domain event stream."""
    return api.StreamConfig(
        name=names.events_stream,
        description="SupportX domain events (outbox relay); replays addressed to one consumer",
        subjects=[f"{names.events_root}.>", f"{names.replay_root}.>"],
        retention=api.RetentionPolicy.LIMITS,
        storage=api.StorageType.FILE,
        discard=api.DiscardPolicy.OLD,
        max_age=settings.events_stream_max_age_hours * 3600.0,
        duplicate_window=float(settings.events_duplicate_window_seconds),
        num_replicas=settings.events_stream_replicas,
        allow_direct=True,
    )


def dlq_stream_config(names: BusNames, settings: Settings) -> api.StreamConfig:
    """Dead letters: messages a consumer gave up on, with the error in headers."""
    return api.StreamConfig(
        name=names.dlq_stream,
        description="SupportX dead letters (make dlq-list / dlq-replay)",
        subjects=[f"{names.dlq_root}.>"],
        retention=api.RetentionPolicy.LIMITS,
        storage=api.StorageType.FILE,
        discard=api.DiscardPolicy.OLD,
        max_age=settings.dlq_max_age_hours * 3600.0,
        duplicate_window=120.0,
        num_replicas=settings.events_stream_replicas,
        allow_direct=True,
    )


async def ensure_stream(js: JetStreamContext, config: api.StreamConfig) -> str:
    """Create or update one stream; returns "created" or "updated" (idempotent)."""
    if config.name is None:  # pragma: no cover - configs above always name the stream
        msg = "stream config needs a name"
        raise ValueError(msg)
    try:
        await js.stream_info(config.name)
    except NotFoundError:
        await js.add_stream(config)
        log.info("stream_created", stream=config.name)
        return "created"
    await js.update_stream(config)
    return "updated"


async def ensure_heartbeat_bucket(js: JetStreamContext, names: BusNames) -> KeyValue:
    """The KV bucket workers write their heartbeats to."""
    try:
        return await js.key_value(names.heartbeat_bucket)
    except BucketNotFoundError:
        return await js.create_key_value(
            api.KeyValueConfig(
                bucket=names.heartbeat_bucket,
                description="SupportX worker heartbeats (relay, consumers)",
                history=1,
                ttl=HEARTBEAT_KEY_TTL_SECONDS,
                storage=api.StorageType.MEMORY,
            )
        )


@dataclass(frozen=True)
class Bus:
    """A connected worker's view of the bus."""

    client: NatsClient
    js: JetStreamContext
    names: BusNames
    heartbeats: KeyValue

    async def close(self) -> None:
        """Drain and close the connection."""
        with contextlib.suppress(nats.errors.Error):
            await self.client.drain()


async def provision(js: JetStreamContext, names: BusNames, settings: Settings) -> KeyValue:
    """Streams and bucket, created or updated to match the settings."""
    await ensure_stream(js, events_stream_config(names, settings))
    await ensure_stream(js, dlq_stream_config(names, settings))
    return await ensure_heartbeat_bucket(js, names)


def _error_logger(component: str) -> Callable[[Exception], Awaitable[None]]:
    async def on_error(error: Exception) -> None:
        log.warning("nats_error", component=component, error_type=type(error).__name__)

    return on_error


async def connect(settings: Settings, component: str) -> Bus:
    """Connect (reconnecting forever on drops), then provision the streams."""
    if settings.nats_url is None:
        msg = "SUPPORTX_NATS_URL is not set (make backend-env)"
        raise RuntimeError(msg)
    client = await nats.connect(
        settings.nats_url.get_secret_value(),
        name=f"{component}@{socket.gethostname()}",
        max_reconnect_attempts=-1,
        reconnect_time_wait=1,
        connect_timeout=max(1, math.ceil(settings.readiness_timeout_seconds)),
        error_cb=_error_logger(component),
    )
    js = client.jetstream()
    names = bus_names(settings)
    heartbeats = await provision(js, names, settings)
    return Bus(client=client, js=js, names=names, heartbeats=heartbeats)
