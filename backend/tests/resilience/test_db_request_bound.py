"""The API's request path against a slow or silent PostgreSQL (the HA smoke's failover).

A server that keeps its TCP connection but never answers (a paused or frozen primary; PgBouncer
waiting on a server that failed over) is still ACKed by the kernel, so pool_pre_ping, keepalive
and TCP_USER_TIMEOUT never fire. Measured before this change: a request-path query waited
122 s (asyncpg's 120 s command_timeout), and lane C reproduced it independently.

Now the request path (`Database.from_settings(..., request_path=True)`, the API only):
- PostgreSQL cancels a request transaction's statement after db_request_statement_timeout_seconds
  (`request_too_slow`, a labelled 503: slow, not down);
- the API's connections give up REQUEST_BACKSTOP_SECONDS later on a silent server
  (`database_unavailable`, a labelled 503), and answer again once it is back;
- workers and jobs (no request_path) keep db_command_timeout_seconds, and a slow statement there
  is never cancelled by the request bound;
- the bound is SET LOCAL, so it never outlives the transaction on a pooled connection.

Own throwaway PostgreSQL container on a random port (never the dev stack's). Runs with
SUPPORTX_RESILIENCE_TESTS=1 (CI job "worker resilience"); needs Docker.
"""

import asyncio
import os
import secrets
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text

from app.core.config import Settings
from app.core.database import (
    DATABASE_UNAVAILABLE,
    REQUEST_BACKSTOP_SECONDS,
    REQUEST_TOO_SLOW,
    Database,
)
from app.core.errors import ServiceUnavailable, install_error_handlers
from app.core.middleware import RequestContextMiddleware
from app.core.request_context import bind_request, clear_request
from app.core.tenancy import TenantContext
from conftest import make_settings

pytestmark = pytest.mark.resilience

POSTGRES_IMAGE = "postgres:16-alpine"
REQUEST_BOUND = 2.0  # seconds: the test's request statement timeout, small to keep it quick
TENANT = TenantContext(uuid.UUID("01900000-0000-7000-8000-0000000000aa"))

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


@pytest.fixture(scope="module")
def postgres() -> Iterator[tuple[str, str]]:
    """A throwaway PostgreSQL; yields (container name, URL)."""
    name = f"supportx-test-dbbound-{secrets.token_hex(4)}"
    port = _free_port()
    password = secrets.token_hex(8)
    _docker(
        "run", "-d", "--name", name, "-e", f"POSTGRES_PASSWORD={password}",
        "-p", f"127.0.0.1:{port}:5432", POSTGRES_IMAGE,
    )  # fmt: skip
    try:
        deadline = time.monotonic() + 60
        while (
            subprocess.run(  # noqa: S603 - fixed docker arguments
                ["docker", "exec", name, "pg_isready", "-U", "postgres"],  # noqa: S607
                capture_output=True,
                check=False,
            ).returncode
            != 0
        ):
            if time.monotonic() > deadline:
                pytest.fail("PostgreSQL did not start within 60 s")
            time.sleep(0.5)
        time.sleep(1.0)  # pg_isready answers a moment before the server takes connections
        yield name, f"postgresql://postgres:{password}@127.0.0.1:{port}/postgres"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)  # noqa: S603, S607


def _settings(url: str) -> Settings:
    return make_settings(
        database_url=SecretStr(url), db_request_statement_timeout_seconds=REQUEST_BOUND
    )


@pytest.fixture
async def request_db(postgres: tuple[str, str]) -> AsyncIterator[Database]:
    database = Database.from_settings(_settings(postgres[1]), request_path=True)
    assert database is not None
    yield database
    await database.engine.dispose()


async def _select(database: Database, sql: str = "SELECT 1") -> object:
    async with database.tenant_session(TENANT) as session:
        return (await session.execute(text(sql))).scalar()


async def _command_timeout(database: Database) -> float | None:
    async with database.engine.connect() as connection:
        raw = await connection.get_raw_connection()
        # asyncpg keeps the connection's command timeout on its private config (untyped).
        timeout: float | None = raw.driver_connection._config.command_timeout  # type: ignore[union-attr]  # noqa: SLF001
        return timeout


async def test_only_the_request_path_gets_the_short_client_bound(
    request_db: Database, postgres: tuple[str, str]
) -> None:
    """Workers and jobs keep db_command_timeout_seconds (the coordinator's condition)."""
    background = Database.from_settings(_settings(postgres[1]))
    assert background is not None
    try:
        assert await _command_timeout(request_db) == REQUEST_BOUND + REQUEST_BACKSTOP_SECONDS
        assert await _command_timeout(background) == background.settings.db_command_timeout_seconds  # type: ignore[union-attr]
    finally:
        await background.engine.dispose()


async def test_a_slow_statement_is_request_too_slow_on_the_request_path_only(
    request_db: Database, postgres: tuple[str, str]
) -> None:
    started = time.monotonic()
    bind_request("test-slow")  # inside a request, as the middleware binds it
    try:
        with pytest.raises(ServiceUnavailable) as refused:
            await _select(request_db, f"SELECT pg_sleep({REQUEST_BOUND + 2})")
    finally:
        clear_request()
    assert refused.value.instance_code == REQUEST_TOO_SLOW
    assert time.monotonic() - started < REQUEST_BOUND + 1.5  # PostgreSQL cancelled it at the bound

    # A worker's or job's session runs the same statement to the end (never the request bound).
    background = Database.from_settings(_settings(postgres[1]))
    assert background is not None
    try:
        slept = f"SELECT 1 FROM pg_sleep({REQUEST_BOUND + 1})"  # noqa: S608 - a constant number
        assert await _select(background, slept) == 1
    finally:
        await background.engine.dispose()


async def test_the_bound_never_outlives_its_transaction_on_a_pooled_connection(
    request_db: Database,
) -> None:
    """SET LOCAL: the next use of the same pooled connection outside a request has no bound."""
    async with request_db.tenant_session(TENANT) as session:
        inside = (await session.execute(text("SHOW statement_timeout"))).scalar()
    assert inside == f"{int(REQUEST_BOUND)}s"  # PostgreSQL shows 2000 ms as "2s"
    async with request_db.engine.connect() as connection:  # the pool's one warm connection
        after = (await connection.execute(text("SHOW statement_timeout"))).scalar()
    assert after == "0"


async def test_a_silent_server_is_database_unavailable_in_time_then_answers_again(
    request_db: Database, postgres: tuple[str, str]
) -> None:
    name, _url = postgres
    assert await _select(request_db) == 1  # warm: a pooled connection exists
    started = time.monotonic()
    assert await _select(request_db) == 1
    assert time.monotonic() - started < 2  # the control: an answering server, at once

    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)  # binds the request ID, as the API does

    @app.get("/probe")
    async def probe() -> dict[str, object]:
        return {"one": await _select(request_db)}

    await asyncio.to_thread(_docker, "pause", name)
    try:
        started = time.monotonic()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            answer = await asyncio.wait_for(client.get("/probe"), 90)
        took = time.monotonic() - started
    finally:
        await asyncio.to_thread(_docker, "unpause", name)
    assert answer.status_code == 503, answer.text
    body = answer.json()
    assert (body["code"], body["message_key"]) == (
        DATABASE_UNAVAILABLE,
        f"errors.{DATABASE_UNAVAILABLE}",
    )
    # Within the client bound plus the rollback's own wait and slack; never asyncpg's 120 s.
    bound = REQUEST_BOUND + REQUEST_BACKSTOP_SECONDS
    assert took < 2 * bound + 5, took

    # Back: a request answers again within a few seconds (pre-ping replaces the dead connection).
    deadline = time.monotonic() + 30
    while True:
        try:
            assert await _select(request_db) == 1
            break
        except Exception:
            if time.monotonic() > deadline:
                raise
            await asyncio.sleep(0.5)


async def test_outside_a_request_the_drivers_own_error_is_kept(request_db: Database) -> None:
    """Startup hooks catch the driver's error on purpose (a down database waits for the next
    start), so only a request being served gets the labelled 503."""
    with pytest.raises(Exception) as raised:  # noqa: PT011 - any driver error, never ours
        await _select(request_db, f"SELECT pg_sleep({REQUEST_BOUND + 2})")
    assert not isinstance(raised.value, ServiceUnavailable)
