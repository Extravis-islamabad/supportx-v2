"""The API's database connections notice a vanished peer in seconds, not after a timeout.

Cluster run 43135183726 (#425): a node with a PgBouncer copy was stopped; pooled connections to
it got no reset and each waited out the command timeout (120 s), so a write came back after 294
of 300 s. Every new connection's TCP socket now has keepalives and, where the platform has it
(Linux in every image), TCP_USER_TIMEOUT.
"""

import socket

import pytest
from sqlalchemy import text

from app.core.database import TCP_KEEPALIVE, TCP_USER_TIMEOUT_MS, create_engine
from tooling import db_testing

pytestmark = pytest.mark.db


async def test_a_new_connection_detects_dead_peers(
    migrated_db: db_testing.ThrowawayDatabase,
) -> None:
    engine = create_engine(migrated_db.app_url, application_name="dead-peers-test")
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            raw = await conn.get_raw_connection()
            transport = raw.driver_connection._transport  # type: ignore[union-attr]  # noqa: SLF001 - asyncpg internal, as in the code
            sock = transport.get_extra_info("socket")
            if sock.family not in (socket.AF_INET, socket.AF_INET6):
                pytest.skip("the test database is on a Unix socket: TCP options do not apply")
            assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) != 0
            if hasattr(socket, "TCP_KEEPIDLE"):
                idle = TCP_KEEPALIVE[0]
                assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE) == idle
            if hasattr(socket, "TCP_USER_TIMEOUT"):
                timeout = sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT)
                assert timeout == TCP_USER_TIMEOUT_MS
    finally:
        await engine.dispose()
