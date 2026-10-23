"""Fan-out merging, rate limits and failure handling (WP-011), with a fake Centrifugo."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from app.shared.events import Actor, EventEnvelope
from app.shared.realtime import (
    ACCESS_CHANGED,
    CentrifugoError,
    Disconnect,
    Publication,
    Publish,
    RealtimeEffects,
    queue,
    record,
)
from app.shared.realtime.centrifugo import Command
from workers.metrics import FanoutMetrics
from workers.realtime_fanout.fanout import Fanout, TokenBucket

TENANT = uuid.UUID("01900000-0000-7000-8000-0000000000a1")
OTHER = uuid.UUID("01900000-0000-7000-8000-0000000000b2")
COMMIT = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


class FakeCentrifugo:
    def __init__(self, *, fail: bool = False) -> None:
        self.batches: list[list[Command]] = []
        self.fail = fail

    async def batch(self, commands: Sequence[Command]) -> int:
        if self.fail:
            msg = "down"
            raise CentrifugoError(msg)
        self.batches.append(list(commands))
        return 0

    @property
    def publishes(self) -> list[Publish]:
        return [c for b in self.batches for c in b if isinstance(c, Publish)]

    @property
    def disconnects(self) -> list[Disconnect]:
        return [c for b in self.batches for c in b if isinstance(c, Disconnect)]


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def envelope(tenant: uuid.UUID = TENANT, seconds: float = 0) -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid.uuid4(),
        event_type="identity_access.user.updated",
        schema_version=1,
        tenant_id=tenant,
        actor=Actor.system("test"),
        occurred_at=COMMIT + timedelta(seconds=seconds),
        aggregate_type="user",
        aggregate_id="x",
        payload={},
    )


def fanout(
    client: FakeCentrifugo, *, rate: float = 1000, **kw: object
) -> tuple[Fanout, FanoutMetrics, Clock]:
    metrics = FanoutMetrics()
    clock = Clock()
    engine = Fanout(
        client,  # type: ignore[arg-type]  # duck-typed fake
        metrics,
        rate=rate,
        clock=clock,
        now=lambda: COMMIT + timedelta(milliseconds=300),
        **kw,  # type: ignore[arg-type]  # test knobs
    )
    return engine, metrics, clock


def list_change(record_id: str, tenant: uuid.UUID = TENANT) -> RealtimeEffects:
    return RealtimeEffects(
        publications=[
            Publication(queue(tenant, "users"), "users.changed", ids=(record_id,), coalesce=True)
        ]
    )


async def test_a_burst_on_one_list_becomes_one_message() -> None:
    client = FakeCentrifugo()
    engine, metrics, _ = fanout(client)
    for i in range(200):
        engine.add(envelope(), list_change(f"u{i % 20}"))
    await engine.flush()
    assert len(client.publishes) == 1
    data = client.publishes[0].data
    assert data["type"] == "users.changed"
    assert data["ids"] == [f"u{i}" for i in range(20)]
    assert metrics.coalesced_total == 199
    assert metrics.publications_total == 1
    assert metrics.lag_percentiles()["p50_ms"] == 300.0  # commit → publish


async def test_too_many_ids_turn_into_a_refresh() -> None:
    client = FakeCentrifugo()
    engine, _, _ = fanout(client, max_ids=5)
    for i in range(6):
        engine.add(envelope(), list_change(f"u{i}"))
    await engine.flush()
    assert client.publishes[0].data == {"type": "users.changed", "ids": [], "refresh": True}


async def test_record_updates_merge_fields_and_keep_the_highest_version() -> None:
    client = FakeCentrifugo()
    engine, _, _ = fanout(client)
    channel = record(TENANT, "users", uuid.UUID(int=1))
    for fields, version in ((("signature",), 4), (("time_zone",), 6), (("signature",), 5)):
        engine.add(
            envelope(),
            RealtimeEffects(
                publications=[
                    Publication(
                        channel,
                        "users.changed",
                        ids=("1",),
                        fields=fields,
                        version=version,
                        actor_id="me",
                    )
                ]
            ),
        )
    await engine.flush()
    assert [p.data for p in client.publishes] == [
        {
            "type": "users.changed",
            "ids": ["1"],
            "fields": ["signature", "time_zone"],
            "version": 6,
            "by": "me",
        }
    ]


async def test_tenants_are_rate_limited_separately_and_the_rest_waits() -> None:
    client = FakeCentrifugo()
    engine, metrics, clock = fanout(client, rate=2)
    for i in range(5):
        engine.add(
            envelope(),
            RealtimeEffects(
                publications=[
                    Publication(
                        record(TENANT, "users", uuid.UUID(int=i)), "users.changed", ids=(str(i),)
                    )
                ]
            ),
        )
    engine.add(envelope(OTHER), list_change("x", OTHER))
    await engine.flush()
    assert len(client.publishes) == 3  # 2 for TENANT, 1 for OTHER
    assert engine.has_work()
    assert metrics.deferred_total == 3
    clock.t += 1.0  # one second later: two more tokens
    await engine.flush()
    assert len(client.publishes) == 5
    clock.t += 1.0
    await engine.flush()
    assert len(client.publishes) == 6
    assert not engine.has_work()


async def test_a_huge_backlog_drops_record_messages_first() -> None:
    client = FakeCentrifugo()
    engine, metrics, _ = fanout(client, backlog_limit=10)
    engine.add(envelope(), list_change("keep"))
    for i in range(20):
        engine.add(
            envelope(),
            RealtimeEffects(
                publications=[
                    Publication(
                        record(TENANT, "users", uuid.UUID(int=i)), "users.changed", ids=(str(i),)
                    )
                ]
            ),
        )
    assert metrics.dropped_total == 11
    await engine.flush()
    assert any(p.channel == queue(TENANT, "users").name for p in client.publishes)


async def test_failures_put_everything_back_for_the_retry() -> None:
    client = FakeCentrifugo(fail=True)
    engine, metrics, _ = fanout(client)
    first = envelope()
    engine.add(
        first,
        RealtimeEffects(
            publications=list_change("a").publications, revoke_users=[uuid.UUID(int=7)]
        ),
    )
    with pytest.raises(CentrifugoError):
        await engine.flush()
    assert metrics.failures_total == 1
    assert engine.has_work()
    # The redelivered event merges into the same message: same content, same idempotency key.
    engine.add(first, list_change("a"))
    client.fail = False
    await engine.flush()
    assert len(client.publishes) == 1
    assert client.publishes[0].data["ids"] == ["a"]
    assert [d.user for d in client.disconnects] == [f"{TENANT}:{uuid.UUID(int=7)}"]
    assert client.disconnects[0].code == ACCESS_CHANGED


async def test_idempotency_key_depends_on_the_events_not_the_attempt() -> None:
    keys = []
    for _ in range(2):
        client = FakeCentrifugo()
        engine, _, _ = fanout(client)
        fixed = envelope().model_copy(update={"event_id": uuid.UUID(int=99)})
        engine.add(fixed, list_change("a"))
        await engine.flush()
        keys.append(client.publishes[0].idempotency_key)
    assert keys[0] == keys[1]
    assert keys[0] is not None


async def test_revocations_are_not_rate_limited_and_are_deduplicated() -> None:
    client = FakeCentrifugo()
    engine, metrics, _ = fanout(client, rate=1)
    user = uuid.UUID(int=3)
    for _ in range(5):
        engine.add(envelope(), RealtimeEffects(revoke_users=[user, uuid.UUID(int=4)]))
    await engine.flush()
    assert sorted(d.user for d in client.disconnects) == [
        f"{TENANT}:{user}",
        f"{TENANT}:{uuid.UUID(int=4)}",
    ]
    assert metrics.revocations_total == 2


def test_token_bucket_refills_at_the_rate() -> None:
    clock = Clock()
    bucket = TokenBucket(10, clock)
    assert bucket.take(15) == 10
    assert bucket.take(1) == 0
    clock.t = 0.5
    assert bucket.take(10) == 5
