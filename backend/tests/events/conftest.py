"""Fixtures for the event bus tests: real PostgreSQL and real NATS JetStream (WP-007).

Every test gets its own bus namespace (random stream/subject/bucket prefix), so it never touches
the dev stack's SUPPORTX_EVENTS stream and cannot see another test's messages. The streams it
created are deleted afterwards (it made them, CLAUDE.md rule h). The outbox table of the
session's throwaway database is emptied before each test for the same reason.

NATS location: SUPPORTX_TEST_NATS_URL, otherwise the dev stack's NATS_PORT. Locally the tests
skip when NATS is down; with SUPPORTX_REQUIRE_NATS_TESTS=1 (CI) that is a failure instead.
"""

import asyncio
import contextlib
import os
import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Iterator
from datetime import timedelta
from typing import Any

import asyncpg
import nats
import nats.errors
import pytest
import pytest_asyncio
from nats.js.errors import NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.modules import discover_modules
from app.core.tenancy import TenantContext
from app.shared.events import (
    ConsumerSpec,
    EventEnvelope,
    EventRegistry,
    install_registry,
    record_event,
)
from app.shared.events import registry as registry_module
from conftest import make_settings
from tests.events.sample import PROBE_MODULE, ProbeHappened
from tooling import db_testing
from workers import bus
from workers.consumers.runner import ConsumerRunner, RetryPolicy
from workers.outbox_relay.relay import OutboxRelay

NATS_TIMEOUT_SECONDS = 3


def nats_url() -> str | None:
    """Where the test NATS server is, if configured."""
    if url := os.environ.get("SUPPORTX_TEST_NATS_URL"):
        return url
    if db_testing.STACK_ENV.is_file():
        env = db_testing._read_env_file(db_testing.STACK_ENV)  # noqa: SLF001 - shared test helper
        return f"nats://127.0.0.1:{env.get('NATS_PORT', '24222')}"
    return None


async def _reachable(url: str) -> bool:
    try:
        client = await nats.connect(
            url, connect_timeout=2, allow_reconnect=False, max_reconnect_attempts=0
        )
    except (nats.errors.Error, OSError, TimeoutError):
        return False
    await client.close()
    return True


@pytest.fixture(scope="session")
def nats_server() -> str:
    """URL of a reachable NATS JetStream server (skips or fails when there is none)."""
    url = nats_url()
    if url is None or not asyncio.run(_reachable(url)):
        reason = "NATS is not reachable (make dev-up / SUPPORTX_TEST_NATS_URL)"
        if os.environ.get("SUPPORTX_REQUIRE_NATS_TESTS") == "1":
            pytest.fail(f"NATS tests are required here but {reason}")
        pytest.skip(reason)
    return url


@pytest.fixture
def bus_settings(nats_server: str, migrated_db: db_testing.ThrowawayDatabase) -> Settings:
    """Settings for one test: a fresh namespace, fast retries, the throwaway database."""
    return make_settings(
        nats_url=nats_server,
        database_url=migrated_db.app_url,
        relay_database_url=migrated_db.relay_url,
        events_namespace=f"t{secrets.token_hex(4)}_",
        events_stream_max_age_hours=1,
        consumer_max_attempts=3,
        consumer_backoff_initial_seconds=0.05,
        consumer_backoff_max_seconds=0.2,
        consumer_ack_wait_seconds=1.0,
        relay_poll_interval_seconds=0.5,
    )


@pytest_asyncio.fixture
async def event_bus(bus_settings: Settings) -> AsyncIterator[bus.Bus]:
    """A connected, provisioned bus in the test's namespace; its streams are deleted after."""
    connected = await bus.connect(bus_settings, "tests")
    try:
        yield connected
    finally:
        for stream in (connected.names.events_stream, connected.names.dlq_stream):
            with contextlib.suppress(NotFoundError):
                await connected.js.delete_stream(stream)
        with contextlib.suppress(NotFoundError):
            await connected.js.delete_key_value(connected.names.heartbeat_bucket)
        await connected.client.close()


@pytest_asyncio.fixture
async def clean_outbox(migrated_db: db_testing.ThrowawayDatabase) -> None:
    """Empty the throwaway database's outbox (rows left by earlier tests in this session)."""
    conn = await asyncpg.connect(migrated_db.admin_url)
    try:
        await conn.execute("DELETE FROM outbox_events")
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def tenant(migrated_db: db_testing.ThrowawayDatabase) -> uuid.UUID:
    """A fresh tenant."""
    from conftest import create_tenant  # noqa: PLC0415 - root conftest helper

    return await create_tenant(migrated_db.migrator_url, "Events tenant")


RelayFactory = Callable[..., OutboxRelay]


@pytest.fixture
def make_relay(event_bus: bus.Bus, bus_settings: Settings, clean_outbox: None) -> RelayFactory:
    """Build relays (connect() / run() them yourself); `cls` swaps in a crashing subclass."""
    del clean_outbox

    def factory(cls: type[OutboxRelay] = OutboxRelay, **overrides: Any) -> OutboxRelay:  # noqa: ANN401 - forwarded keyword arguments
        if bus_settings.relay_database_url is None:  # pragma: no cover - set by bus_settings
            raise AssertionError
        values: dict[str, Any] = {
            "dsn": bus_settings.relay_database_url.get_secret_value(),
            "js": event_bus.js,
            "names": event_bus.names,
            "batch_size": 100,
            "poll_interval": bus_settings.relay_poll_interval_seconds,
            "publish_timeout": 5.0,
            "retention": timedelta(hours=1),
            "purge_interval": 3600.0,
            **overrides,
        }
        return cls(**values)

    return factory


RunnerFactory = Callable[..., ConsumerRunner]


@pytest.fixture
def make_runner(event_bus: bus.Bus, bus_settings: Settings, app_db: Database) -> RunnerFactory:
    """Build consumer runners for a ConsumerSpec; `cls` swaps in a crashing subclass."""

    def factory(spec: ConsumerSpec, cls: type[ConsumerRunner] = ConsumerRunner) -> ConsumerRunner:
        return cls(
            spec,
            js=event_bus.js,
            names=event_bus.names,
            database=app_db,
            retry=RetryPolicy.from_settings(bus_settings, spec),
            ack_wait=bus_settings.consumer_ack_wait_seconds,
        )

    return factory


async def emit(
    db: Database, tenant_id: uuid.UUID, note: str = "hello", count: int = 1
) -> list[EventEnvelope]:
    """Commit `count` ProbeHappened events in ONE transaction; returns their envelopes."""
    async with db.tenant_session(TenantContext(tenant_id)) as session:
        return [
            await record_event(
                session, ProbeHappened(note=f"{note}-{i}"), aggregate_id=uuid.uuid4()
            )
            for i in range(count)
        ]


async def wait_for(
    condition: Callable[[], Awaitable[bool]], within: float = 10.0, interval: float = 0.05
) -> None:
    """Poll `condition` until true, or fail the test after `within` seconds."""
    async with asyncio.timeout(within):
        # Polling is the point: the condition reads the database or the stream, not an Event.
        while not await condition():  # noqa: ASYNC110
            await asyncio.sleep(interval)


async def stream_message_ids(event_bus: bus.Bus) -> list[str]:
    """Nats-Msg-Id of every message in the test's events stream, in stream order."""
    info = await event_bus.js.stream_info(event_bus.names.events_stream)
    ids: list[str] = []
    for seq in range(info.state.first_seq, info.state.last_seq + 1):
        if not info.state.messages:
            break
        raw = await event_bus.js.get_msg(event_bus.names.events_stream, seq)
        ids.append(str((raw.headers or {}).get("Nats-Msg-Id")))
    return ids


async def outbox_rows(admin_url: str) -> list[asyncpg.Record]:
    """Every outbox row (as the superuser), oldest first."""
    conn = await asyncpg.connect(admin_url)
    try:
        return await conn.fetch(
            "SELECT id, tenant_id, event_type, published_at, publish_attempts, last_error, envelope"
            " FROM outbox_events ORDER BY id"
        )
    finally:
        await conn.close()


async def run_until(
    task_factories: list[Callable[[asyncio.Event], Coroutine[Any, Any, None]]],
    condition: Callable[[], Awaitable[bool]],
    within: float = 15.0,
) -> list[BaseException | None]:
    """Run workers until `condition` holds, stop them, return how each ended (None = cleanly)."""
    stop = asyncio.Event()
    tasks = [asyncio.create_task(factory(stop)) for factory in task_factories]
    try:
        await wait_for(condition, within)
    finally:
        stop.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
    return [result if isinstance(result, BaseException) else None for result in results]


Recorder = list[tuple[EventEnvelope, AsyncSession | None]]


@pytest.fixture(autouse=True)
def probe_events() -> Iterator[EventRegistry]:
    """The app's events plus the test-only probe.item.happened, for the test's duration."""
    previous = registry_module._active  # noqa: SLF001 - restore exactly what was installed
    registry = EventRegistry.from_modules([*discover_modules(), PROBE_MODULE])
    install_registry(registry)
    try:
        yield registry
    finally:
        registry_module._active = previous  # noqa: SLF001
