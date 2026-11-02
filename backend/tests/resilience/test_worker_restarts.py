"""PostgreSQL and NATS restart under running workers; events flow again (must-fix before pilot).

Own throwaway containers (never the dev stack's): a PostgreSQL and a NATS JetStream on random
ports, a fresh migrated database, and the real `workers.outbox_relay` and `workers.consumers`
processes pointed at them through environment variables only. Events are incident-created
events; the notification consumer claims each one exactly once in `processed_events`, which is
what "no lost or duplicated effects" means here.

1. events flow;
2. PostgreSQL restarts while events are written before and after: the relay's readiness goes
   unready during the outage, every event is published and claimed once afterwards;
3. NATS restarts the same way;
4. both workers are still running, nothing reached the dead-letter stream;
5. a worker whose database stays away past its give-up time exits with code 1.

Runs with SUPPORTX_RESILIENCE_TESTS=1 (CI job "worker resilience"); needs Docker.
"""

import asyncio
import contextlib
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import nats
import pytest

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.work_items.events import WorkItemCreated
from app.shared.events import BusNames, install_registry
from app.shared.events.outbox import record_event
from conftest import create_tenant
from tooling.db_testing import DbTestConfig, ThrowawayDatabase, create

pytestmark = pytest.mark.resilience

BACKEND = Path(__file__).resolve().parents[2]
POSTGRES_IMAGE = "pgvector/pgvector:0.8.7-pg16-bookworm"
NATS_IMAGE = "nats:2.15.1-alpine"
CONSUMER = "notifications__dispatch"
WAIT = 60.0

if os.environ.get("SUPPORTX_RESILIENCE_TESTS") != "1" or shutil.which("docker") is None:
    pytest.skip("set SUPPORTX_RESILIENCE_TESTS=1 (needs Docker)", allow_module_level=True)


def _docker(*args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed docker arguments
        ["docker", *args],  # noqa: S607 - docker from PATH, as the developer runs it
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class Stack:
    postgres: str
    nats: str
    admin_password: str
    pg_port: int
    nats_port: int
    db: ThrowawayDatabase
    namespace: str

    @property
    def nats_url(self) -> str:
        return f"nats://127.0.0.1:{self.nats_port}"


def _wait_postgres(url: str) -> None:
    async def ping() -> bool:
        try:
            conn = await asyncpg.connect(url, timeout=2)
        except (OSError, asyncpg.PostgresError, TimeoutError):
            return False
        await conn.close()
        return True

    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        if asyncio.run(ping()):
            return
        time.sleep(0.5)
    pytest.fail("postgres did not come up")


@pytest.fixture(scope="module")
def stack() -> Iterator[Stack]:
    tag = secrets.token_hex(4)
    password = secrets.token_hex(12)
    postgres = f"sx-resilience-pg-{tag}"
    bus = f"sx-resilience-nats-{tag}"
    # Fixed host ports: a random one (-p ::5432) would change when the container restarts.
    pg_port, nats_port = _free_port(), _free_port()
    _docker(
        "run", "-d", "--name", postgres, "-e", f"POSTGRES_PASSWORD={password}",
        "-p", f"127.0.0.1:{pg_port}:5432", POSTGRES_IMAGE,
    )  # fmt: skip
    _docker("run", "-d", "--name", bus, "-p", f"127.0.0.1:{nats_port}:4222", NATS_IMAGE, "-js")
    try:
        admin = f"postgresql://postgres:{password}@127.0.0.1:{pg_port}/postgres"
        _wait_postgres(admin)
        config = DbTestConfig(
            admin_url=admin,
            app_password=secrets.token_hex(8),
            migrator_password=secrets.token_hex(8),
            relay_password=secrets.token_hex(8),
            pgbouncer=None,
        )
        db = create(config)
        yield Stack(postgres, bus, password, pg_port, nats_port, db, f"res{tag}")
    finally:
        for container in (postgres, bus):
            with contextlib.suppress(subprocess.CalledProcessError):
                _docker("rm", "-f", container)


LOGS = Path(os.environ.get("SUPPORTX_RESILIENCE_LOGS", "/tmp"))  # noqa: S108 - test logs only


def _worker(
    stack: Stack, module: str, *, give_up: float = 300.0
) -> tuple[subprocess.Popen[bytes], int]:
    ops_port = _free_port()
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("SUPPORTX_")},
        "SUPPORTX_PROFILE": "test",
        "SUPPORTX_DATABASE_URL": stack.db.app_direct_url,
        "SUPPORTX_RELAY_DATABASE_URL": stack.db.relay_url,
        "SUPPORTX_NATS_URL": stack.nats_url,
        "SUPPORTX_EVENTS_NAMESPACE": stack.namespace,
        "SUPPORTX_METRICS_EXPORTER": "prometheus",
        "SUPPORTX_METRICS_HOST": "127.0.0.1",
        "SUPPORTX_METRICS_PORT": str(ops_port),
        "SUPPORTX_WORKER_GIVE_UP_SECONDS": str(give_up),
        "SUPPORTX_WORKER_SCHEDULES_ENABLED": "false",
        "SUPPORTX_RELAY_POLL_INTERVAL_SECONDS": "1",
        "SUPPORTX_HEARTBEAT_INTERVAL_SECONDS": "1",
    }
    log = (LOGS / f"resilience-{stack.namespace}-{module}.log").open("ab")
    process = subprocess.Popen(  # noqa: S603 - our own worker module
        [sys.executable, "-m", f"workers.{module}"],
        cwd=BACKEND,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    return process, ops_port


def _until_ready(*ports: int) -> None:
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        if all(_ready(port) is True for port in ports):
            return
        time.sleep(0.5)
    pytest.fail("workers did not become ready")


def _ready(port: int) -> bool | None:
    """True/False from the worker's /readyz; None when its ops server does not answer."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=1) as answer:
            return bool(answer.status == 200)
    except urllib.error.HTTPError:
        return False
    except OSError:
        return None


async def _emit(stack: Stack, tenant: uuid.UUID, count: int) -> list[uuid.UUID]:
    database = Database(create_engine(stack.db.app_direct_url, application_name="resilience"))
    ids: list[uuid.UUID] = []
    try:
        async with database.tenant_session(TenantContext(tenant)) as session:
            for _ in range(count):
                item = uuid.uuid4()
                envelope = await record_event(
                    session,
                    WorkItemCreated(
                        work_item_id=item,
                        type="incident",
                        display_id="INC-1",
                        status="new",
                        status_category="open",
                    ),
                    aggregate_id=item,
                )
                ids.append(envelope.event_id)
    finally:
        await database.dispose()
    return ids


async def _counts(stack: Stack, ids: list[uuid.UUID]) -> tuple[int, int]:
    """(published outbox rows, processed claims) among `ids`."""
    conn = await asyncpg.connect(stack.db.admin_url)
    try:
        published = await conn.fetchval(
            "SELECT count(*) FROM outbox_events WHERE id = ANY($1) AND published_at IS NOT NULL",
            ids,
        )
        claimed = await conn.fetchval(
            "SELECT count(*) FROM processed_events WHERE consumer = $1 AND event_id = ANY($2)",
            CONSUMER,
            ids,
        )
    finally:
        await conn.close()
    return int(published), int(claimed)


def _until_delivered(stack: Stack, ids: list[uuid.UUID]) -> None:
    deadline = time.monotonic() + WAIT
    counts = (0, 0)
    while time.monotonic() < deadline:
        counts = asyncio.run(_counts(stack, ids))
        if counts == (len(ids), len(ids)):
            return
        time.sleep(0.5)
    pytest.fail(f"{len(ids)} events, published and claimed: {counts}")


def _dead_letters(stack: Stack) -> int:
    async def count() -> int:
        client = await nats.connect(stack.nats_url)
        try:
            info = await client.jetstream().stream_info(BusNames(stack.namespace).dlq_stream)
        except nats.js.errors.NotFoundError:
            return 0
        finally:
            await client.close()
        return int(info.state.messages)

    return asyncio.run(count())


def _emit_now(stack: Stack, tenant: uuid.UUID, count: int) -> list[uuid.UUID]:
    return asyncio.run(_emit(stack, tenant, count))


def test_events_flow_through_postgres_and_nats_restarts(stack: Stack) -> None:
    install_registry_for_tests()
    tenant = asyncio.run(create_tenant(stack.db.migrator_url, "Resilience"))
    relay, relay_ops = _worker(stack, "outbox_relay")
    consumers, consumers_ops = _worker(stack, "consumers")
    try:
        _until_ready(relay_ops, consumers_ops)
        sent = _emit_now(stack, tenant, 5)
        _until_delivered(stack, sent)
        assert _ready(relay_ops) is True

        # PostgreSQL restarts; events written just before and right after.
        sent += _emit_now(stack, tenant, 5)
        _docker("stop", "-t", "5", stack.postgres)
        unready = False
        for _ in range(20):  # the relay notices the outage and says so
            if _ready(relay_ops) is False:
                unready = True
                break
            time.sleep(0.5)
        _docker("start", stack.postgres)
        _wait_postgres(stack.db.admin_url)
        sent += _emit_now(stack, tenant, 5)
        _until_delivered(stack, sent)
        assert unready, "the relay reported ready while PostgreSQL was down"

        # NATS restarts (JetStream keeps its streams on disk).
        sent += _emit_now(stack, tenant, 5)
        _docker("restart", "-t", "2", stack.nats)
        sent += _emit_now(stack, tenant, 5)
        _until_delivered(stack, sent)

        assert relay.poll() is None, "the relay died"
        assert consumers.poll() is None, "the consumers worker died"
        assert _dead_letters(stack) == 0
        deadline = time.monotonic() + 20
        while _ready(relay_ops) is not True and time.monotonic() < deadline:
            time.sleep(0.5)
        assert _ready(relay_ops) is True, "the relay stayed unready after recovering"
    finally:
        for process in (relay, consumers):
            process.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(10)
            if process.poll() is None:
                process.kill()


def test_a_worker_exits_non_zero_when_its_database_stays_away(stack: Stack) -> None:
    relay, _ = _worker(stack, "outbox_relay", give_up=4)
    try:
        time.sleep(3)  # started and connected
        assert relay.poll() is None
        _docker("stop", "-t", "2", stack.postgres)
        code = relay.wait(60)
        assert code == 1
    finally:
        if relay.poll() is None:
            relay.kill()
        _docker("start", stack.postgres)
        _wait_postgres(stack.db.admin_url)


def install_registry_for_tests() -> None:
    """record_event needs the event registry (the app installs it at startup)."""
    from app.core.modules import discover_modules  # noqa: PLC0415 - test set-up only
    from app.shared.events import EventRegistry  # noqa: PLC0415

    install_registry(EventRegistry.from_modules(discover_modules()))
