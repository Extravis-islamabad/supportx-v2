"""Outbox relay: committed outbox rows → NATS JetStream (architecture.md §4.2, §6.5; WP-007).

Loop, per relay process:

1. Wait for `NOTIFY supportx_outbox` (sent by a trigger when an event's transaction commits) or
   the poll interval, whichever comes first. The poll only catches a missed notification, e.g.
   while the LISTEN connection was being re-established.
2. In one transaction: take up to `batch_size` unpublished rows in event-ID order with
   `FOR UPDATE SKIP LOCKED` (a second relay skips rows the first holds and takes the next ones),
   publish each to `events.<tenant>.<event_type>` with `Nats-Msg-Id = event_id`, wait for every
   JetStream acknowledgement, then set `published_at` on exactly the acknowledged rows and commit.
3. Repeat until the outbox is empty; purge published rows older than the retention period once
   per purge interval, together with expired idempotency keys and old consumer records (WP-012).

Crash anywhere before the commit in step 2 → the rows stay unpublished and the next relay
publishes them again. JetStream drops the repeat because it has seen that Nats-Msg-Id within
the duplicate window, and consumers are idempotent anyway, so nothing is lost or applied twice.

The relay connects as supportx_relay straight to PostgreSQL (not PgBouncer: LISTEN needs a
session). That role can read and mark outbox rows of every tenant and nothing else.
"""

import asyncio
import contextlib
import time
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

import asyncpg
from nats.js import JetStreamContext

from app.core.logging import get_logger
from app.shared.events import OUTBOX_CHANNEL, BusNames
from workers.metrics import RelayMetrics
from workers.resilience import Connectivity, unavailable

log = get_logger(__name__)

SELECT_BATCH = """
SELECT id, tenant_id, event_type, envelope::text AS envelope,
       envelope->>'traceparent' AS traceparent
FROM outbox_events
WHERE published_at IS NULL
ORDER BY id
LIMIT $1
FOR UPDATE SKIP LOCKED
"""
MARK_PUBLISHED = """
UPDATE outbox_events
SET published_at = now(), updated_at = now(), publish_attempts = publish_attempts + 1,
    last_error = NULL
WHERE id = ANY($1::uuid[])
"""
MARK_FAILED = """
UPDATE outbox_events
SET publish_attempts = publish_attempts + 1, last_error = $2, updated_at = now()
WHERE id = $1
"""
OLDEST_UNPUBLISHED_AGE = """
SELECT EXTRACT(EPOCH FROM now() - created_at)::float8
FROM outbox_events WHERE published_at IS NULL ORDER BY id LIMIT 1
"""
# Never touches an unpublished row: the RLS delete policy for supportx_relay only allows
# `published_at IS NOT NULL`, whatever this statement says.
PURGE_CHUNK = """
DELETE FROM outbox_events
WHERE id IN (
    SELECT id FROM outbox_events
    WHERE published_at IS NOT NULL AND published_at < now() - make_interval(secs => $1)
    ORDER BY published_at
    LIMIT $2
)
"""
# Housekeeping of two other tables (WP-012, migration 0010). The relay's RLS policies there only
# show it expired keys and consumer records older than 7 days, so these can never remove anything
# younger, whatever the retention setting says.
PURGE_EXPIRED_KEYS_CHUNK = """
DELETE FROM idempotency_keys
WHERE ctid IN (SELECT ctid FROM idempotency_keys WHERE expires_at < now() LIMIT $1)
"""
PURGE_PROCESSED_CHUNK = """
DELETE FROM processed_events
WHERE ctid IN (
    SELECT ctid FROM processed_events
    WHERE created_at < now() - make_interval(secs => $1)
    LIMIT $2
)
"""
PURGE_CHUNK_SIZE = 5000
_RECOVERABLE = (OSError, asyncpg.PostgresConnectionError, asyncpg.InterfaceError)


def _describe(error: BaseException) -> str:
    """Stable, single-line error text for `last_error` (no payload data is ever in it)."""
    text = " ".join(str(error).split())[:300]
    return f"{type(error).__name__}: {text}" if text else type(error).__name__


class OutboxRelay:
    """One relay instance. Several may run at once (SKIP LOCKED keeps them apart)."""

    def __init__(  # noqa: PLR0913 - keyword-only tuning knobs, all from settings
        self,
        *,
        dsn: str,
        js: JetStreamContext,
        names: BusNames,
        batch_size: int,
        poll_interval: float,
        publish_timeout: float,
        retention: timedelta,
        purge_interval: float,
        processed_retention: timedelta = timedelta(days=30),
        metrics: RelayMetrics | None = None,
        connectivity: Connectivity | None = None,
    ) -> None:
        self.dsn = dsn
        self.js = js
        self.names = names
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self.publish_timeout = publish_timeout
        self.retention = retention
        self.purge_interval = purge_interval
        self.processed_retention = processed_retention
        self.metrics = metrics or RelayMetrics()
        self.connectivity = connectivity or Connectivity(give_up_after=float("inf"))
        self._pool: asyncpg.Pool | None = None
        self._listener: asyncpg.Connection | None = None
        self._wake = asyncio.Event()
        self._last_purge = 0.0  # monotonic; 0 = purge on the first loop

    # --- connections ----------------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the work pool and the LISTEN connection."""
        self._pool = await asyncpg.create_pool(
            self.dsn, min_size=1, max_size=2, server_settings={"application_name": "outbox-relay"}
        )
        self._listener = await asyncpg.connect(
            self.dsn, server_settings={"application_name": "outbox-relay-listen"}
        )
        await self._listener.add_listener(OUTBOX_CHANNEL, self._on_notify)
        self._wake.set()  # drain whatever accumulated while we were away

    async def close(self) -> None:
        """Close both connections (safe to call twice)."""
        if self._listener is not None:
            with contextlib.suppress(*_RECOVERABLE):
                await self._listener.close(timeout=2)
            self._listener = None
        if self._pool is not None:
            with contextlib.suppress(*_RECOVERABLE):
                await asyncio.wait_for(self._pool.close(), 5)
            self._pool = None

    def _on_notify(self, *_args: object) -> None:
        self._wake.set()

    @property
    def pool(self) -> asyncpg.Pool:
        """The work pool (connect() first)."""
        if self._pool is None:
            msg = "relay is not connected"
            raise RuntimeError(msg)
        return self._pool

    # --- main loop ------------------------------------------------------------------------------

    async def run(self, stop: asyncio.Event) -> None:
        """Relay until `stop` is set, riding out PostgreSQL restarts (workers/resilience.py).

        Rows stay unpublished while the database or the bus is away and go out, in order, once
        both answer; past `worker_give_up_seconds` WorkerUnrecoverable ends the process.
        """
        while not stop.is_set():
            try:
                await self.connect()
                self.connectivity.up("database")
                log.info("relay_started", stream=self.names.events_stream)
                await self._loop(stop)
            except Exception as exc:
                if unavailable(exc) != "database" and not isinstance(exc, _RECOVERABLE):
                    raise
                self.connectivity.down("database", exc)
                await self.close()
                await self.connectivity.wait("database", stop)
        await self.close()

    async def _loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            self._wake.clear()  # a NOTIFY that arrives while draining sets it again
            await self.drain()
            await self.maybe_purge()
            if self._listener is None or self._listener.is_closed():
                raise ConnectionResetError  # LISTEN connection lost: reconnect
            await self._wait_for_work(stop)

    async def _wait_for_work(self, stop: asyncio.Event) -> None:
        waiters = [asyncio.ensure_future(self._wake.wait()), asyncio.ensure_future(stop.wait())]
        try:
            await asyncio.wait(waiters, timeout=self.poll_interval, return_when="FIRST_COMPLETED")
        finally:
            for waiter in waiters:
                waiter.cancel()

    async def drain(self) -> int:
        """Publish batches until the outbox is empty or publishing stops making progress."""
        total = 0
        while True:
            selected, published = await self.publish_batch()
            total += published
            if selected and not published and self.connectivity.connected is False:
                self.connectivity.check()  # the bus is away: give up in time, never spin
            if selected < self.batch_size or published == 0:
                return total

    async def publish_batch(self) -> tuple[int, int]:
        """One batch: returns (rows taken, rows published)."""
        async with self.pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(SELECT_BATCH, self.batch_size)
            if not rows:
                return 0, 0
            results = await self._publish_all(rows)
            published = [
                row["id"]
                for row, result in zip(rows, results, strict=True)
                if not isinstance(result, BaseException)
            ]
            failed = [
                (row["id"], _describe(result))
                for row, result in zip(rows, results, strict=True)
                if isinstance(result, BaseException)
            ]
            await self.before_mark(published)
            if published:
                await conn.execute(MARK_PUBLISHED, published)
            if failed:
                await conn.executemany(MARK_FAILED, failed)
        if published:
            self.connectivity.up("bus")
        elif failed and all(_bus_away(r) for r in results):
            # Every publish failed because NATS is away: the rows wait (MARK_FAILED kept the
            # attempt count and reason) and go out once it is back.
            self.connectivity.down("bus", next(r for r in results if isinstance(r, BaseException)))
        duplicates = sum(1 for result in results if result is _DUPLICATE)
        self.metrics.published(len(published), duplicates)
        self.metrics.failed(len(failed))
        if failed:
            log.warning("relay_publish_failed", count=len(failed), first_error=failed[0][1])
        return len(rows), len(published)

    async def before_mark(self, published: Sequence[Any]) -> None:
        """Hook between JetStream's acknowledgements and marking rows. Tests crash here."""

    async def _publish_all(self, rows: Sequence[asyncpg.Record]) -> list[object]:
        # Coroutines start in list order and each writes its PUB before awaiting, so one relay
        # hands a batch to the server in event-ID order (see events.md, "Ordering").
        tasks = [self._publish(row) for row in rows]
        try:
            async with asyncio.timeout(self.publish_timeout + 1):
                return list(await asyncio.gather(*tasks, return_exceptions=True))
        except TimeoutError as exc:
            return [exc] * len(rows)

    async def _publish(self, row: asyncpg.Record) -> object:
        headers = {"Nats-Msg-Id": str(row["id"])}
        if row["traceparent"]:
            headers["traceparent"] = row["traceparent"]
        ack = await self.js.publish(
            self.names.event_subject(row["tenant_id"], row["event_type"]),
            row["envelope"].encode(),
            timeout=self.publish_timeout,
            stream=self.names.events_stream,
            headers=headers,
        )
        return _DUPLICATE if ack.duplicate else True

    # --- housekeeping ---------------------------------------------------------------------------

    async def maybe_purge(self) -> int:
        """Purge (outbox and housekeeping) at most once per purge interval; returns outbox rows."""
        now = time.monotonic()
        if self._last_purge and now - self._last_purge < self.purge_interval:
            return 0
        self._last_purge = now
        purged = await self.purge()
        await self.purge_housekeeping()
        return purged

    async def _delete_in_chunks(self, statement: str, *args: object) -> int:
        total = 0
        while True:
            async with self.pool.acquire() as conn:
                status = await conn.execute(statement, *args, PURGE_CHUNK_SIZE)
            deleted = int(status.rsplit(" ", 1)[-1])
            total += deleted
            if deleted < PURGE_CHUNK_SIZE:
                return total

    async def purge_housekeeping(self) -> dict[str, int]:
        """Delete expired idempotency keys and consumer records older than their retention."""
        purged = {
            "idempotency_keys": await self._delete_in_chunks(PURGE_EXPIRED_KEYS_CHUNK),
            "processed_events": await self._delete_in_chunks(
                PURGE_PROCESSED_CHUNK, self.processed_retention.total_seconds()
            ),
        }
        if any(purged.values()):
            log.info(
                "housekeeping_purged",
                retention_days=self.processed_retention.total_seconds() / 86400,
                **purged,
            )
        return purged

    async def purge(self) -> int:
        """Delete every published row older than the retention period, in chunks."""
        total = 0
        while True:
            async with self.pool.acquire() as conn:
                status = await conn.execute(
                    PURGE_CHUNK, self.retention.total_seconds(), PURGE_CHUNK_SIZE
                )
            deleted = int(status.rsplit(" ", 1)[-1])
            total += deleted
            if deleted < PURGE_CHUNK_SIZE:
                break
        if total:
            self.metrics.purged_total += total
            log.info(
                "outbox_purged", rows=total, retention_hours=self.retention.total_seconds() / 3600
            )
        return total

    async def refresh_backlog_age(self) -> float:
        """Age in seconds of the oldest unpublished row (0 when the outbox is empty)."""
        try:
            async with self.pool.acquire() as conn:
                age = await conn.fetchval(OLDEST_UNPUBLISHED_AGE)
        except (*_RECOVERABLE, RuntimeError):
            return self.metrics.oldest_unpublished_age_seconds
        self.metrics.oldest_unpublished_age_seconds = float(age or 0.0)
        return self.metrics.oldest_unpublished_age_seconds


def _bus_away(result: object) -> bool:
    return isinstance(result, BaseException) and (
        unavailable(result) == "bus" or isinstance(result, TimeoutError)
    )


class _Duplicate:
    """JetStream acknowledged the message as a duplicate (it was already in the stream)."""

    def __bool__(self) -> bool:
        return True  # still counts as published: the event is in the stream


_DUPLICATE = _Duplicate()
