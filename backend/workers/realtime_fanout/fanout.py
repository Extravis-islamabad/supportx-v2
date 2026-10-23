"""Coalescing, per-tenant rate limiting and publishing (architecture.md §8.4; WP-011).

Events are routed to publications as they arrive and merged while they wait for the next flush:

* list messages (`coalesce=True`) for the same channel and type become one `{type, ids}` message;
  past `max_ids` records the IDs are dropped and the message says `refresh: true` (refetch all);
* record messages for the same record merge their changed fields and keep the highest version.

A flush sends at most `rate` messages per tenant per second (token bucket); the rest wait for
the next flush and keep merging. Revocations (cut connections) are never rate limited. A tenant
backlog over `backlog_limit` drops its oldest record messages (lists stay, they are bounded by
the number of list channels). Deferred messages live in memory: a crash loses at most UI hints
the screens reconcile on reconnect anyway (docs/architecture/realtime.md).
"""

import hashlib
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.shared.events import EventEnvelope
from app.shared.realtime import (
    ACCESS_CHANGED,
    CentrifugoClient,
    Disconnect,
    Publication,
    Publish,
    RealtimeEffects,
    realtime_user,
)
from workers.metrics import FanoutMetrics

BATCH_COMMANDS = 500

MessageKey = tuple[str, str, tuple[str, ...]]


@dataclass
class Outgoing:
    """One message being built from one or more publications."""

    channel: str
    type: str
    coalesce: bool
    ids: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    version: int | None = None
    actor_id: str | None = None
    refresh: bool = False
    event_ids: set[uuid.UUID] = field(default_factory=set)
    first_commit: datetime | None = None

    def merge(self, publication: Publication, envelope: EventEnvelope, max_ids: int) -> None:
        """Fold one more publication (from `envelope`) into this message."""
        if not self.refresh:
            for record_id in publication.ids:
                if record_id not in self.ids:
                    self.ids.append(record_id)
            if len(self.ids) > max_ids:
                self.ids, self.refresh = [], True
        for name in publication.fields:
            if name not in self.fields:
                self.fields.append(name)
        if publication.version is not None:
            self.version = max(self.version or 0, publication.version)
        self.actor_id = publication.actor_id or self.actor_id
        self.event_ids.add(envelope.event_id)
        if self.first_commit is None or envelope.occurred_at < self.first_commit:
            self.first_commit = envelope.occurred_at

    def data(self) -> dict[str, Any]:
        """The payload (IDs, field names, version, actor; never record contents)."""
        body: dict[str, Any] = {"type": self.type, "ids": list(self.ids)}
        if self.refresh:
            body["refresh"] = True
        if self.fields:
            body["fields"] = list(self.fields)
        if self.version is not None:
            body["version"] = self.version
        if self.actor_id is not None:
            body["by"] = self.actor_id
        return body

    def idempotency_key(self) -> str:
        """Same events, same message → same key: a retried flush is not shown twice."""
        digest = hashlib.sha256(f"{self.channel}|{self.type}|".encode())
        for event_id in sorted(self.event_ids):
            digest.update(event_id.bytes)
        return digest.hexdigest()[:32]


class TokenBucket:
    """`rate` per second, bursts up to `rate`."""

    def __init__(self, rate: float, clock: Callable[[], float]) -> None:
        self.rate = rate
        self.tokens = rate
        self.clock = clock
        self.updated = clock()

    def take(self, wanted: int) -> int:
        """How many of `wanted` may go now (they are spent)."""
        now = self.clock()
        self.tokens = min(self.rate, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        granted = min(wanted, int(self.tokens))
        self.tokens -= granted
        return granted


class Fanout:
    """Pending messages and revocations per tenant, flushed to Centrifugo."""

    def __init__(  # noqa: PLR0913 - tuning knobs injected for tests
        self,
        client: CentrifugoClient,
        metrics: FanoutMetrics,
        *,
        rate: float,
        max_ids: int = 50,
        backlog_limit: int = 2000,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.client = client
        self.metrics = metrics
        self.rate = rate
        self.max_ids = max_ids
        self.backlog_limit = backlog_limit
        self.clock = clock
        self.now = now
        self.pending: dict[uuid.UUID, dict[MessageKey, Outgoing]] = {}
        self.revocations: dict[uuid.UUID, set[uuid.UUID]] = {}
        self.buckets: dict[uuid.UUID, TokenBucket] = {}

    def add(self, envelope: EventEnvelope, effects: RealtimeEffects) -> None:
        """Route results of one event into the pending messages."""
        tenant = envelope.tenant_id
        messages = self.pending.setdefault(tenant, {})
        for publication in effects.publications:
            name = publication.channel.name
            key: MessageKey = (
                (name, publication.type, ())
                if publication.coalesce
                else (name, publication.type, publication.ids)
            )
            existing = messages.get(key)
            if existing is not None:
                self.metrics.coalesced(1)
            else:
                existing = messages[key] = Outgoing(name, publication.type, publication.coalesce)
            existing.merge(publication, envelope, self.max_ids)
        if effects.revoke_users:
            self.revocations.setdefault(tenant, set()).update(effects.revoke_users)
        self._trim(tenant)

    def _trim(self, tenant: uuid.UUID) -> None:
        messages = self.pending[tenant]
        excess = len(messages) - self.backlog_limit
        if excess <= 0:
            return
        oldest_records = [k for k, m in messages.items() if not m.coalesce][:excess]
        for key in oldest_records:
            del messages[key]
        self.metrics.dropped(len(oldest_records))

    def has_work(self) -> bool:
        """Anything waiting to be sent."""
        return any(self.pending.values()) or any(self.revocations.values())

    def _take(self) -> tuple[list[Outgoing], list[tuple[uuid.UUID, uuid.UUID]]]:
        """What may go now (rate limit), removed from the pending state."""
        sending: list[Outgoing] = []
        for tenant, messages in self.pending.items():
            if not messages:
                continue
            bucket = self.buckets.get(tenant)
            if bucket is None:
                bucket = self.buckets[tenant] = TokenBucket(self.rate, self.clock)
            granted = bucket.take(len(messages))
            keys = list(messages)[:granted]
            sending += [messages.pop(k) for k in keys]
            self.metrics.deferred_total += len(messages)
        revoking = [(t, u) for t, users in self.revocations.items() for u in sorted(users)]
        self.revocations = {}
        return sending, revoking

    def _restore(
        self, sending: Iterable[Outgoing], revoking: Iterable[tuple[uuid.UUID, uuid.UUID]]
    ) -> None:
        """Put back what could not be sent (the next flush tries again)."""
        for message in sending:
            tenant = uuid.UUID(message.channel.split(":")[1])
            key: MessageKey = (
                (message.channel, message.type, ())
                if message.coalesce
                else (message.channel, message.type, tuple(message.ids))
            )
            self.pending.setdefault(tenant, {})[key] = message
        for tenant, user in revoking:
            self.revocations.setdefault(tenant, set()).add(user)

    async def flush(self) -> None:
        """Publish what the rate limits allow, then cut revoked users' connections.

        Raises CentrifugoError (after putting everything back) when Centrifugo is unreachable;
        the caller then naks the batch's messages so they are delivered again. The kept copy may
        go out before the redelivery arrives; the redelivered event then builds the same message
        with the same idempotency key, which Centrifugo drops (publish idempotency, minutes).
        """
        sending, revoking = self._take()
        if not sending and not revoking:
            return
        try:
            publishes = [
                Publish(m.channel, m.data(), idempotency_key=m.idempotency_key()) for m in sending
            ]
            failed = 0
            for start in range(0, len(publishes), BATCH_COMMANDS):
                failed += await self.client.batch(publishes[start : start + BATCH_COMMANDS])
            disconnects = [
                Disconnect(realtime_user(t, u), ACCESS_CHANGED, "access changed")
                for t, u in revoking
            ]
            for start in range(0, len(disconnects), BATCH_COMMANDS):
                await self.client.batch(disconnects[start : start + BATCH_COMMANDS])
        except Exception:
            self._restore(sending, revoking)
            self.metrics.failures_total += 1
            raise
        now = self.now()
        self.metrics.failures_total += failed
        self.metrics.published(
            len(sending) - failed,
            [(now - m.first_commit).total_seconds() for m in sending if m.first_commit],
        )
        self.metrics.revocations_total += len(revoking)
