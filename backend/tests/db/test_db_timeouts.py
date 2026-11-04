"""A database server that stops answering fails within the client's limits (WP-014b).

The node-loss test showed the case: a pooled connection to a server whose node vanished gets no
reset, so without a limit asyncpg waits on the kernel's retries for minutes. A proxy in front of
the real PostgreSQL stands in for that server: it forwards normally, then goes silent without
closing anything.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.core.database import create_engine, reporting_command_timeout
from tooling.db_testing import ThrowawayDatabase


class SilentProxy:
    """Forwards TCP to `target` until `silence()`; then drops every byte and closes nothing."""

    def __init__(self, host: str, port: int) -> None:
        self.target = (host, port)
        self.silent = False
        self._writers: list[asyncio.StreamWriter] = []

    async def _pipe(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while data := await reader.read(65536):
            if not self.silent:
                writer.write(data)
                await writer.drain()

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        up_reader, up_writer = await asyncio.open_connection(*self.target)
        self._writers += [writer, up_writer]
        await asyncio.gather(
            self._pipe(reader, up_writer), self._pipe(up_reader, writer), return_exceptions=True
        )

    def silence(self) -> None:
        self.silent = True

    @asynccontextmanager
    async def running(self) -> AsyncIterator[int]:
        server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        try:
            yield server.sockets[0].getsockname()[1]
        finally:
            for writer in self._writers:
                writer.close()
            server.close()


def _through(url: str, port: int) -> str:
    return make_url(url).set(host="127.0.0.1", port=port).render_as_string(hide_password=False)


@pytest.mark.db
async def test_a_query_to_a_server_that_went_silent_fails_within_the_command_limit(
    migrated_db: ThrowawayDatabase,
) -> None:
    target = make_url(migrated_db.app_direct_url)
    proxy = SilentProxy(target.host or "127.0.0.1", target.port or 5432)
    async with proxy.running() as port:
        engine = create_engine(
            _through(migrated_db.app_direct_url, port),
            application_name="timeout-test",
            connect_timeout=5,
            command_timeout=2,
        )
        try:
            async with engine.connect() as connection:
                assert (await connection.execute(text("SELECT 1"))).scalar() == 1
                proxy.silence()  # the server's node is gone: no answer, no reset
                started = time.monotonic()
                with pytest.raises(Exception):  # noqa: B017, PT011 - asyncpg's TimeoutError, wrapped by SQLAlchemy
                    await connection.execute(text("SELECT 1"))
                assert time.monotonic() - started < 6
        finally:
            await engine.dispose()


@pytest.mark.db
async def test_connecting_to_a_server_that_never_answers_fails_within_the_connect_limit(
    migrated_db: ThrowawayDatabase,
) -> None:
    async def accept_and_stay_silent(
        _reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await asyncio.sleep(60)
        writer.close()

    server = await asyncio.start_server(accept_and_stay_silent, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    engine = create_engine(
        _through(migrated_db.app_direct_url, port),
        application_name="timeout-test",
        connect_timeout=1,
        command_timeout=2,
    )
    try:
        started = time.monotonic()
        with pytest.raises(Exception):  # noqa: B017, PT011 - asyncpg's TimeoutError, wrapped by SQLAlchemy
            async with engine.connect():
                pass
        assert time.monotonic() - started < 4
    finally:
        await engine.dispose()
        server.close()


def test_the_reporting_pool_never_cuts_a_report_short() -> None:
    # The longest background report the platform allows still ends by PostgreSQL's own
    # statement_timeout (report_timeout), well before the client gives up.
    for background in (900.0, 3600.0):
        settings = Settings(report_background_timeout_seconds=background)
        assert reporting_command_timeout(settings) >= background + 60
    assert reporting_command_timeout(Settings()) > Settings().db_command_timeout_seconds
