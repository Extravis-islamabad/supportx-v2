"""Durable JetStream pull consumers for module-declared handlers (architecture.md §6.5; WP-007).

For every message:

1. Parse the envelope. Not an envelope at all → straight to the dead-letter stream (retrying a
   malformed message cannot help).
2. Transactional consumer: open a tenant session for the event's tenant (SET LOCAL
   app.tenant_id, as for an API request), claim (consumer, event_id) in processed_events, run the
   handler, commit. Claim already present → the event was applied before: skip the handler.
3. Success → ack. Failure → nak with exponential backoff; on attempt `max_attempts` → publish the
   message with the error to the dead-letter stream, then terminate it here.

A crash between commit and ack is harmless: the redelivery finds the claim and is acked without
running the handler again. A crash before commit rolls back the claim and the effects together,
and the redelivery (after ack_wait) runs the handler again from scratch.

Ordering: one runner processes its messages one at a time, in stream order. A retried message is
redelivered after its backoff, so messages behind it may be processed first: consumers must not
assume order across retries (docs/architecture/events.md, "Ordering").
"""

import asyncio
import contextlib
from datetime import UTC, datetime

import nats.errors
from nats.aio.msg import Msg
from nats.js import JetStreamContext, api
from opentelemetry import propagate, trace
from pydantic import ValidationError

from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.shared.events import BusNames, ConsumerSpec, EventEnvelope, claim
from workers.metrics import ConsumerMetrics

log = get_logger(__name__)
tracer = trace.get_tracer("supportx.consumers")

FETCH_BATCH = 64
FETCH_TIMEOUT_SECONDS = 1.0
MAX_ACK_PENDING = 1000
ERROR_HEADER_LIMIT = 500


class RetryPolicy:
    """Exponential backoff: initial, 2x, 4x ... capped; dead letter after `max_attempts`."""

    def __init__(self, *, max_attempts: int, initial: float, maximum: float) -> None:
        self.max_attempts = max_attempts
        self.initial = initial
        self.maximum = maximum

    def delay(self, attempt: int) -> float:
        """Seconds to wait before delivery number `attempt + 1`."""
        return float(min(self.initial * 2 ** max(attempt - 1, 0), self.maximum))

    def exhausted(self, attempt: int) -> bool:
        """Whether delivery number `attempt` was the last one allowed."""
        return attempt >= self.max_attempts

    @classmethod
    def from_settings(cls, settings: Settings, spec: ConsumerSpec) -> "RetryPolicy":
        """Settings defaults, overridden per consumer."""
        return cls(
            max_attempts=spec.max_attempts or settings.consumer_max_attempts,
            initial=settings.consumer_backoff_initial_seconds,
            maximum=settings.consumer_backoff_max_seconds,
        )


def _one_line(text: str, limit: int = ERROR_HEADER_LIMIT) -> str:
    return " ".join(text.split())[:limit]


class ConsumerRunner:
    """Runs one ConsumerSpec as a durable pull consumer."""

    def __init__(  # noqa: PLR0913 - collaborators injected for testability
        self,
        spec: ConsumerSpec,
        *,
        js: JetStreamContext,
        names: BusNames,
        database: Database | None,
        retry: RetryPolicy,
        ack_wait: float,
        metrics: ConsumerMetrics | None = None,
    ) -> None:
        if spec.transactional and database is None:
            msg = f"consumer {spec.name} is transactional but no database is configured"
            raise RuntimeError(msg)
        self.spec = spec
        self.js = js
        self.names = names
        self.database = database
        self.retry = retry
        self.ack_wait = spec.ack_wait_seconds or ack_wait
        self.metrics = metrics or ConsumerMetrics()
        self._subscription: JetStreamContext.PullSubscription | None = None

    @property
    def name(self) -> str:
        """Durable consumer name."""
        return self.spec.name

    def config(self) -> api.ConsumerConfig:
        """The durable consumer as declared in code."""
        filters = [self.names.event_filter(p) for p in self.spec.event_types]
        filters.append(self.names.replay_filter(self.spec.name))
        return api.ConsumerConfig(
            name=self.spec.name,
            durable_name=self.spec.name,
            description=f"SupportX consumer {self.spec.name}",
            deliver_policy=(
                api.DeliverPolicy.NEW if self.spec.deliver_from == "new" else api.DeliverPolicy.ALL
            ),
            ack_policy=api.AckPolicy.EXPLICIT,
            ack_wait=self.ack_wait,
            # Unlimited on the server: this runner counts attempts and dead-letters itself, so a
            # message is never silently dropped by max_deliver.
            max_deliver=-1,
            max_ack_pending=MAX_ACK_PENDING,
            filter_subjects=filters,
        )

    async def ensure(self) -> None:
        """Create the durable consumer, or update it to the declared configuration."""
        await self.js.add_consumer(self.names.events_stream, self.config())

    async def subscribe(self) -> None:
        """Bind to the durable consumer (after ensure())."""
        self._subscription = await self.js.pull_subscribe_bind(
            durable=self.spec.name, stream=self.names.events_stream
        )

    async def run(self, stop: asyncio.Event) -> None:
        """Fetch and handle messages until `stop` is set."""
        if self._subscription is None:
            await self.ensure()
            await self.subscribe()
        subscription = self._subscription
        if subscription is None:  # pragma: no cover - subscribe() just set it
            raise RuntimeError
        log.info("consumer_started", consumer=self.name)
        while not stop.is_set():
            try:
                messages = await subscription.fetch(FETCH_BATCH, timeout=FETCH_TIMEOUT_SECONDS)
            except (nats.errors.TimeoutError, TimeoutError):
                continue
            except nats.errors.Error:
                log.warning("consumer_fetch_failed", consumer=self.name, exc_info=True)
                await asyncio.sleep(1)
                continue
            for message in messages:
                await self.handle(message)
        with contextlib.suppress(nats.errors.Error):
            await subscription.unsubscribe()
        self._subscription = None  # a later run() binds afresh

    async def handle(self, message: Msg) -> None:
        """Process one delivery: ack, nak with backoff, or dead-letter."""
        attempt = message.metadata.num_delivered or 1
        try:
            envelope = EventEnvelope.from_json(message.data)
        except ValidationError as exc:
            await self.dead_letter(message, None, exc, attempt)
            return
        try:
            with tracer.start_as_current_span(
                f"consume {envelope.event_type}",
                context=propagate.extract({"traceparent": envelope.traceparent or ""}),
                attributes={
                    "supportx.consumer": self.name,
                    "supportx.event_id": str(envelope.event_id),
                },
            ):
                applied = await self.process(envelope)
        except Exception as exc:  # noqa: BLE001 - any handler failure is retried, then dead-lettered
            if self.retry.exhausted(attempt):
                await self.dead_letter(message, envelope, exc, attempt)
            else:
                ConsumerMetrics.bump(self.metrics.retried, self.name)
                delay = self.retry.delay(attempt)
                log.warning(
                    "event_handler_failed",
                    consumer=self.name,
                    event_id=str(envelope.event_id),
                    event_type=envelope.event_type,
                    attempt=attempt,
                    retry_in_seconds=delay,
                    error_type=type(exc).__name__,
                )
                await message.nak(delay=delay)
            return
        await self.before_ack(envelope)
        await message.ack()
        counter = self.metrics.processed if applied else self.metrics.duplicates
        ConsumerMetrics.bump(counter, self.name)

    async def process(self, envelope: EventEnvelope) -> bool:
        """Run the handler once in effect. False when the event was already processed."""
        if not self.spec.transactional or self.database is None:
            await self.spec.handler(envelope, None)
            return True
        async with self.database.tenant_session(TenantContext(envelope.tenant_id)) as session:
            if not await claim(session, self.name, envelope):
                return False
            await self.spec.handler(envelope, session)
        return True

    async def before_ack(self, envelope: EventEnvelope) -> None:
        """Hook between commit and ack. Tests crash here."""

    async def dead_letter(
        self, message: Msg, envelope: EventEnvelope | None, error: Exception, attempt: int
    ) -> None:
        """Park the message in the DLQ with the error, then stop redelivering it."""
        tenant = envelope.tenant_id if envelope else "unknown"
        event_type = envelope.event_type if envelope else "unknown.unknown.unknown"
        headers = {
            # Same original message → same DLQ ID: a crash after this publish cannot park it twice.
            "Nats-Msg-Id": f"{self.name}:{message.metadata.sequence.stream}",
            "Supportx-Consumer": self.name,
            "Supportx-Original-Subject": message.subject,
            "Supportx-Attempts": str(attempt),
            "Supportx-Error-Type": type(error).__name__,
            "Supportx-Error": _one_line(str(error)) or type(error).__name__,
            "Supportx-Failed-At": datetime.now(UTC).isoformat(),
        }
        await self.js.publish(
            self.names.dlq_subject(self.name, tenant, event_type),
            message.data,
            stream=self.names.dlq_stream,
            headers=headers,
        )
        await message.term()
        ConsumerMetrics.bump(self.metrics.dead_lettered, self.name)
        log.error(
            "event_dead_lettered",
            consumer=self.name,
            event_id=str(envelope.event_id) if envelope else None,
            event_type=event_type,
            attempts=attempt,
            error_type=type(error).__name__,
        )

    async def refresh_lag(self) -> int | None:
        """Pending + unacknowledged messages for this consumer, from the server."""
        try:
            info = await self.js.consumer_info(self.names.events_stream, self.name)
        except (nats.errors.Error, OSError):
            return None
        lag = int((info.num_pending or 0) + (info.num_ack_pending or 0))
        self.metrics.lag[self.name] = lag
        return lag
