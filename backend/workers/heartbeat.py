"""Worker heartbeats in a NATS key-value bucket (WP-007).

Each running relay and consumer worker writes `<kind>.<instance>` every few seconds with a small
JSON document (time + counters). Keys expire on their own a minute after the last write, so a
dead worker disappears. The API's /ready reads the bucket (app/modules/system/infra/probes.py)
and `make events-stats` prints it.
"""

import asyncio
import contextlib
import json
import os
import re
import secrets
import socket
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Literal

import nats.errors
from nats.js.kv import KeyValue

from app.core.logging import get_logger

log = get_logger(__name__)

WorkerKind = Literal["relay", "consumers", "fanout"]
_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def instance_id() -> str:
    """`<host>-<pid>-<random>`, safe as a KV key token."""
    host = _UNSAFE_KEY_CHARS.sub("_", socket.gethostname())[:40]
    return f"{host}-{os.getpid()}-{secrets.token_hex(3)}"


class Heartbeat:
    """Writes this worker's heartbeat until stopped."""

    def __init__(
        self,
        bucket: KeyValue,
        kind: WorkerKind,
        *,
        interval: float,
        stats: Callable[[], Mapping[str, Any]],
        instance: str | None = None,
    ) -> None:
        self.bucket = bucket
        self.key = f"{kind}.{instance or instance_id()}"
        self.interval = interval
        self.stats = stats

    async def beat(self) -> None:
        """Write one heartbeat now."""
        document = {"at": datetime.now(UTC).isoformat(), "stats": dict(self.stats())}
        await self.bucket.put(self.key, json.dumps(document, default=str).encode())

    async def run(self, stop: asyncio.Event) -> None:
        """Beat every `interval` seconds; a failed write is logged, never fatal."""
        while not stop.is_set():
            try:
                await self.beat()
            except (nats.errors.Error, OSError):
                log.warning("heartbeat_failed", key=self.key)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), self.interval)
        with contextlib.suppress(nats.errors.Error, OSError):
            await self.bucket.delete(self.key)  # leave cleanly: /ready stops counting us at once
