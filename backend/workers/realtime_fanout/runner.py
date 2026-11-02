"""The fan-out consumer: NATS → routes → Fanout → Centrifugo (WP-011).

A durable JetStream consumer like every other (WP-007: same configuration, retries, dead
letters), run in windows instead of one message at a time:

1. Wait for the first message (long poll), then keep fetching for `window` seconds.
2. Route every message (module RealtimeRoutes, in a read-only tenant session per tenant).
   A message whose route fails is nak'ed with backoff, and dead-lettered after max attempts.
3. Flush: publish (coalesced, rate limited) and revoke. Success → ack the window's messages.
   Centrifugo unreachable → nak them all (they come back and merge into the same messages).

New consumers start at the end of the stream (`deliver_from="new"`): replaying history to
screens that are not open would be noise, and missed messages are recovered from Centrifugo's
channel history or by refetching (architecture.md §8.3).
"""

import asyncio
import contextlib
import time
from collections import defaultdict
from typing import TYPE_CHECKING

import nats.errors
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.shared.events import BusNames, ConsumerSpec, EventEnvelope
from app.shared.realtime import CentrifugoError, RealtimeEffects, RealtimeRegistry
from workers.consumers.runner import ConsumerRunner, RetryPolicy
from workers.metrics import ConsumerMetrics
from workers.realtime_fanout.fanout import Fanout
from workers.resilience import Connectivity, database_reachable, unavailable

if TYPE_CHECKING:
    import uuid

log = get_logger(__name__)

CONSUMER_NAME = "realtime__fanout"
WAIT_SECONDS = 1.0
WINDOW_BATCH = 256
RETRY_DELAY_SECONDS = 1.0


async def _not_called(_envelope: EventEnvelope, _session: object) -> None:  # pragma: no cover
    raise RuntimeError


def consumer_spec(registry: RealtimeRegistry) -> ConsumerSpec:
    """The durable consumer for every event type some module routes."""
    return ConsumerSpec(
        name=CONSUMER_NAME,
        event_types=tuple(registry.event_types()),
        handler=_not_called,  # this runner routes in windows, not through a per-message handler
        transactional=False,
        deliver_from="new",
    )


class FanoutRunner(ConsumerRunner):
    """ConsumerRunner (config, ensure, dead letters, lag) with windowed processing."""

    def __init__(  # noqa: PLR0913 - collaborators injected for testability
        self,
        *,
        registry: RealtimeRegistry,
        fanout: Fanout,
        database: Database,
        window: float,
        js: JetStreamContext,
        names: BusNames,
        retry: RetryPolicy,
        ack_wait: float,
        metrics: ConsumerMetrics | None = None,
        connectivity: Connectivity | None = None,
    ) -> None:
        super().__init__(
            consumer_spec(registry),
            js=js,
            names=names,
            database=None,  # routes get their own read sessions (process_window)
            retry=retry,
            ack_wait=ack_wait,
            metrics=metrics,
            connectivity=connectivity,
        )
        self.registry = registry
        self.fanout = fanout
        self.routes_database = database
        self.window = window

    async def run(self, stop: asyncio.Event) -> None:
        """Windows of messages until `stop` is set, riding out NATS and database restarts."""
        self._stop = stop
        while self._subscription is None and not stop.is_set():
            try:
                await self.ensure()
                await self.subscribe()
            except (nats.errors.Error, OSError) as exc:
                self.connectivity.down("bus", exc)
                await self.connectivity.wait("bus", stop)
        if stop.is_set():
            return
        subscription = self._subscription
        if subscription is None:  # pragma: no cover - subscribe() just set it
            raise RuntimeError
        log.info("fanout_started", consumer=self.name, event_types=self.spec.event_types)
        while not stop.is_set():
            messages = await self.collect(subscription)
            if messages:
                try:
                    await self._window_through_outages(messages)
                except (nats.errors.Error, OSError) as exc:
                    # Acknowledging failed: NATS is away; the window comes back after ack_wait.
                    self.connectivity.down("bus", exc)
            elif self.fanout.has_work():  # deferred by the rate limit
                with contextlib.suppress(CentrifugoError):
                    await self.fanout.flush()
        with contextlib.suppress(nats.errors.Error):
            await subscription.unsubscribe()
        self._subscription = None

    async def collect(self, subscription: JetStreamContext.PullSubscription) -> list[Msg]:
        """Wait for a first message (long poll), then gather more for one window."""
        # With rate-limited messages waiting, come back after one window to send them.
        first_wait = self.window if self.fanout.has_work() else WAIT_SECONDS
        try:
            messages = list(await subscription.fetch(WINDOW_BATCH, timeout=max(first_wait, 0.05)))
        except (nats.errors.TimeoutError, TimeoutError):
            return []
        except (nats.errors.Error, OSError) as exc:
            log.warning("fanout_fetch_failed", exc_info=True)
            self.connectivity.down("bus", exc)
            await self.connectivity.wait("bus", self._stop)
            return []
        deadline = time.monotonic() + self.window
        while len(messages) < WINDOW_BATCH and (left := deadline - time.monotonic()) > 0:
            try:
                messages += await subscription.fetch(WINDOW_BATCH - len(messages), timeout=left)
            except (nats.errors.TimeoutError, TimeoutError):
                break
        return messages

    async def _window_through_outages(self, messages: list[Msg]) -> None:
        """`process_window`, held and retried while the database is away (not attempts)."""
        while True:
            try:
                await self.process_window(messages)
            except Exception as exc:
                dependency = unavailable(exc)
                if dependency is None and isinstance(exc, (OSError, TimeoutError)):
                    reachable = await database_reachable(self.routes_database.engine)
                    dependency = None if reachable else "database"
                if dependency is None or self._stop.is_set():
                    raise
                self.connectivity.down(dependency, exc)
                for message in messages:
                    with contextlib.suppress(nats.errors.Error, OSError):
                        await message.in_progress()
                await self.connectivity.wait(dependency, self._stop)
                continue
            self.connectivity.up("database")
            return

    async def process_window(self, messages: list[Msg]) -> None:
        """Route, flush, then ack (or nak everything for another try)."""
        routed: list[Msg] = []
        by_tenant: dict[uuid.UUID, list[tuple[Msg, EventEnvelope]]] = defaultdict(list)
        for message in messages:
            try:
                envelope = EventEnvelope.from_json(message.data)
            except ValidationError as exc:
                await self.dead_letter(message, None, exc, message.metadata.num_delivered or 1)
                continue
            by_tenant[envelope.tenant_id].append((message, envelope))
        for tenant, items in by_tenant.items():
            async with self.routes_database.tenant_session(TenantContext(tenant)) as session:
                for message, envelope in items:
                    if await self._route(message, envelope, session):
                        routed.append(message)
        try:
            await self.fanout.flush()
        except CentrifugoError:
            log.warning("fanout_publish_failed", messages=len(routed), exc_info=True)
            for message in routed:
                await message.nak(delay=RETRY_DELAY_SECONDS)
            return
        for message in routed:
            await message.ack()
            ConsumerMetrics.bump(self.metrics.processed, self.name)

    async def _route(self, message: Msg, envelope: EventEnvelope, session: AsyncSession) -> bool:
        """Route one event into the pending publications; False when it failed (retried)."""
        try:
            for route in self.registry.routes_for(envelope.event_type):
                effects: RealtimeEffects = await route.route(envelope, session)
                self.fanout.add(envelope, effects)
        except Exception as exc:
            if unavailable(exc) is not None:
                raise  # the database is away: hold the whole window instead
            await self._failed(message, envelope, exc)
            return False
        self.fanout.metrics.events_total += 1
        return True

    async def _failed(self, message: Msg, envelope: EventEnvelope, error: Exception) -> None:
        attempt = message.metadata.num_delivered or 1
        if self.retry.exhausted(attempt):
            await self.dead_letter(message, envelope, error, attempt)
            return
        ConsumerMetrics.bump(self.metrics.retried, self.name)
        log.warning(
            "fanout_route_failed",
            event_id=str(envelope.event_id),
            event_type=envelope.event_type,
            attempt=attempt,
            error_type=type(error).__name__,
        )
        await message.nak(delay=self.retry.delay(attempt))
