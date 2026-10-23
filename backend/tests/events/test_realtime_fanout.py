"""Realtime fan-out end to end through the outbox and NATS (WP-011).

Real PostgreSQL and NATS JetStream; Centrifugo is a recording fake here (the integration test in
tests/integration talks to the real one). Events are committed with record_event, published by
the relay, routed by the module routes and flushed by the fan-out runner.
"""

import uuid
from collections.abc import Sequence

import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.core.database import Database
from app.core.modules import discover_modules
from app.core.tenancy import TenantContext
from app.modules.identity_access.events import UserRoleChanged, UserUpdated
from app.modules.licensing.events import EntitlementChanged
from app.shared.events import Actor, record_event
from app.shared.realtime import CentrifugoError, Disconnect, Publish, RealtimeRegistry
from app.shared.realtime.centrifugo import Command
from tests.db.test_users_api import seed_users
from tests.events.conftest import RelayFactory, run_until
from tooling.db_testing import ThrowawayDatabase
from workers import bus
from workers.consumers.runner import RetryPolicy
from workers.metrics import FanoutMetrics
from workers.realtime_fanout.fanout import Fanout
from workers.realtime_fanout.runner import FanoutRunner, consumer_spec

pytestmark = [pytest.mark.db, pytest.mark.nats]


class RecordingCentrifugo:
    def __init__(self, failures: int = 0) -> None:
        self.commands: list[Command] = []
        self.failures = failures

    async def batch(self, commands: Sequence[Command]) -> int:
        if self.failures:
            self.failures -= 1
            msg = "centrifugo down"
            raise CentrifugoError(msg)
        # Like Centrifugo: a second publication with the same idempotency key is dropped.
        seen = {c.idempotency_key for c in self.published()}
        self.commands += [
            c for c in commands if not (isinstance(c, Publish) and c.idempotency_key in seen)
        ]
        return 0

    def published(self) -> list[Publish]:
        return [c for c in self.commands if isinstance(c, Publish)]

    def channels(self) -> dict[str, list[dict[str, object]]]:
        found: dict[str, list[dict[str, object]]] = {}
        for p in self.published():
            found.setdefault(p.channel, []).append(dict(p.data))
        return found

    def disconnected(self) -> list[str]:
        return [c.user for c in self.commands if isinstance(c, Disconnect)]


def runner_for(
    event_bus: bus.Bus, settings: Settings, db: Database, client: RecordingCentrifugo
) -> FanoutRunner:
    registry = RealtimeRegistry.build(discover_modules())
    return FanoutRunner(
        registry=registry,
        fanout=Fanout(client, FanoutMetrics(), rate=1000),  # type: ignore[arg-type]  # recording fake
        database=db,
        window=0.25,
        js=event_bus.js,
        names=event_bus.names,
        retry=RetryPolicy.from_settings(settings, consumer_spec(registry)),
        ack_wait=settings.consumer_ack_wait_seconds,
    )


async def users(migrated_db: ThrowawayDatabase, tenant: uuid.UUID, count: int) -> list[uuid.UUID]:
    return await seed_users(
        migrated_db,
        tenant,
        [{"display_name": f"Rt {i}", "user_type": "technician"} for i in range(count)],
    )


async def test_a_role_assignment_reaches_the_users_screens_and_cuts_their_connection(
    event_bus: bus.Bus,
    bus_settings: Settings,
    app_db: Database,
    make_relay: RelayFactory,
    migrated_db: ThrowawayDatabase,
    tenant: uuid.UUID,
) -> None:
    (user,) = await users(migrated_db, tenant, 1)
    role = uuid.uuid4()
    admin = uuid.uuid4()
    client = RecordingCentrifugo()
    runner = runner_for(event_bus, bus_settings, app_db, client)
    await runner.ensure()  # new consumers start at the end of the stream
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        await record_event(
            session,
            UserRoleChanged(user_id=user, role_id=role, change="assigned"),
            aggregate_id=user,
            actor=Actor.user(admin),
        )
    relay = make_relay()
    await relay.connect()

    async def delivered() -> bool:
        return bool(client.disconnected())

    outcome = await run_until([relay.run, runner.run], delivered)
    assert outcome == [None, None]
    channels = client.channels()
    assert channels[f"t:{tenant}:user:{user}"] == [{"type": "access.changed", "ids": [str(user)]}]
    assert channels[f"t:{tenant}:users:{user}"] == [
        {"type": "users.changed", "ids": [str(user)], "fields": ["roles"], "by": str(admin)}
    ]
    assert channels[f"t:{tenant}:queue:roles"] == [{"type": "roles.changed", "ids": [str(role)]}]
    assert f"t:{tenant}:queue:roles.signal" in channels  # rule-bound audience: no IDs
    assert client.disconnected() == [f"{tenant}:{user}"]
    assert all(str(user) not in str(v) for k, v in channels.items() if k.endswith(".signal"))


async def test_a_burst_of_profile_edits_becomes_one_list_message(
    event_bus: bus.Bus,
    bus_settings: Settings,
    app_db: Database,
    make_relay: RelayFactory,
    migrated_db: ThrowawayDatabase,
    tenant: uuid.UUID,
) -> None:
    edited = await users(migrated_db, tenant, 30)
    client = RecordingCentrifugo()
    runner = runner_for(event_bus, bus_settings, app_db, client)
    await runner.ensure()
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        for user in edited:
            for version in (2, 3):
                await record_event(
                    session,
                    UserUpdated(user_id=user, changed_fields=["signature"]),
                    aggregate_id=user,
                    aggregate_version=version,
                )
    relay = make_relay()
    await relay.connect()
    list_channel = f"t:{tenant}:queue:users"

    async def all_records_out() -> bool:
        records = [c for c in client.channels() if c.startswith(f"t:{tenant}:users:")]
        return len(records) == len(edited)

    await run_until([relay.run, runner.run], all_records_out)
    messages = client.channels()[list_channel]
    # 60 events in one commit: one list message (or very few, if the window split them).
    assert len(messages) <= 2
    assert sorted({i for m in messages for i in m["ids"]}) == sorted(str(u) for u in edited)  # type: ignore[attr-defined]
    record = client.channels()[f"t:{tenant}:users:{edited[0]}"]
    assert record == [
        {"type": "users.changed", "ids": [str(edited[0])], "fields": ["signature"], "version": 3}
    ]
    assert runner.fanout.metrics.coalesced_total >= 60
    assert client.disconnected() == []  # a signature edit changes no access


async def test_a_plan_change_tells_everyone_and_cuts_every_active_user(
    event_bus: bus.Bus,
    bus_settings: Settings,
    app_db: Database,
    make_relay: RelayFactory,
    migrated_db: ThrowawayDatabase,
    tenant: uuid.UUID,
) -> None:
    active = await users(migrated_db, tenant, 3)
    client = RecordingCentrifugo(failures=1)  # Centrifugo is briefly down: retried, sent once
    runner = runner_for(event_bus, bus_settings, app_db, client)
    await runner.ensure()
    async with app_db.tenant_session(TenantContext(tenant)) as session:
        await session.execute(
            text("UPDATE users SET status = 'disabled' WHERE id = :id"), {"id": active[0]}
        )
        await record_event(
            session,
            EntitlementChanged(source="subscription", changed_fields=["edition"]),
            aggregate_id=tenant,
        )
    relay = make_relay()
    await relay.connect()

    async def delivered() -> bool:
        return bool(client.published())

    await run_until([relay.run, runner.run], delivered)
    assert client.channels()[f"t:{tenant}:broadcast"] == [
        {"type": "entitlements.changed", "ids": [], "fields": ["edition"]}
    ]
    # After the outage a user may be cut twice (kept copy + redelivery): harmless, they rejoin.
    assert set(client.disconnected()) == {f"{tenant}:{u}" for u in active[1:]}
