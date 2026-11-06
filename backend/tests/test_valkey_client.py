"""One Valkey client factory: a single server, or the master Sentinel names (WP-014b)."""

import asyncio
from typing import Any

import pytest
import valkey.exceptions
from pydantic import SecretStr
from valkey.asyncio.sentinel import SentinelConnectionPool

from app.core import valkey as core_valkey
from app.core.config import Settings


def _settings(**values: object) -> Settings:
    return Settings.load(env_file=None, profile="test").model_copy(update=values)


def test_sentinel_hosts_parse_with_the_default_port() -> None:
    assert core_valkey.sentinel_hosts("a:26380, b ,c:1") == [("a", 26380), ("b", 26379), ("c", 1)]
    for bad in ("", " , ", "a:port"):
        with pytest.raises(ValueError, match="SENTINELS"):
            core_valkey.sentinel_hosts(bad)


def test_no_url_is_a_clear_error() -> None:
    with pytest.raises(core_valkey.ValkeyNotConfiguredError):
        core_valkey.client(_settings(valkey_url=None))


async def test_without_sentinels_it_is_the_url_as_before() -> None:
    found = core_valkey.client(_settings(valkey_url=SecretStr("valkey://:pw@cache:6379/3")))
    kwargs = found.connection_pool.connection_kwargs
    assert (kwargs["host"], kwargs["port"], kwargs["db"], kwargs["password"]) == (
        "cache",
        6379,
        3,
        "pw",
    )
    await found.aclose()


async def test_with_sentinels_it_asks_them_for_the_master() -> None:
    found = core_valkey.client(
        _settings(
            valkey_url=SecretStr("valkeys://:data-pw@ignored:6379/2"),
            valkey_sentinels="s1:26379,s2:26379",
            valkey_sentinel_master="supportx-ha",
            valkey_sentinel_password=SecretStr("sentinel-pw"),
        ),
        socket_timeout=1.5,
    )
    pool = found.connection_pool
    assert isinstance(pool, SentinelConnectionPool)
    assert pool.service_name == "supportx-ha"
    kwargs = pool.connection_kwargs
    assert (kwargs["db"], kwargs["password"], kwargs["socket_timeout"]) == (2, "data-pw", 1.5)
    assert "host" not in kwargs  # the master's address comes from the sentinels
    assert pool.connection_class.__name__ == "SentinelManagedSSLConnection"  # valkeys:// kept
    sentinels = pool.sentinel_manager.sentinels
    assert [(s.connection_pool.connection_kwargs["host"]) for s in sentinels] == ["s1", "s2"]
    assert all(s.connection_pool.connection_kwargs["password"] == "sentinel-pw" for s in sentinels)
    await found.aclose()


def _retries(kwargs: dict[str, Any]) -> tuple[int, list[type[Exception]]]:  # Any: valkey kwargs
    # valkey-py's Retry keeps its count private and unannotated; read only to check the bound.
    return kwargs["retry"]._retries, kwargs["retry_on_error"]  # noqa: SLF001


async def test_both_paths_retry_a_lost_connection_a_bounded_number_of_times() -> None:
    plain = core_valkey.client(_settings(valkey_url=SecretStr("valkey://cache:6379/0")))
    ha = core_valkey.client(
        _settings(valkey_url=SecretStr("valkey://ignored:6379/0"), valkey_sentinels="s1:26379")
    )
    for found in (plain, ha):
        count, errors = _retries(found.connection_pool.connection_kwargs)
        assert count == core_valkey.RETRIES
        assert set(errors) == {valkey.exceptions.ConnectionError, valkey.exceptions.TimeoutError}
        await found.aclose()
    # A caller can still turn it off (the readiness probe does).
    once = core_valkey.client(
        _settings(valkey_url=SecretStr("valkey://cache:6379/0")), retry=None, retry_on_error=[]
    )
    assert once.connection_pool.connection_kwargs["retry"] is None
    await once.aclose()


async def test_a_pooled_connection_the_server_dropped_is_retried_not_an_error() -> None:
    """The failover case: the pooled socket points at a master that went away."""
    connections = 0

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal connections
        connections += 1
        pings = 0
        while data := await reader.read(4096):
            writer.write(b"+OK\r\n" * data.upper().count(b"SETINFO"))
            if b"PING" in data.upper():
                if connections == 1 and pings == 1:
                    writer.close()  # the second command on the first socket: dropped
                    return
                pings += 1
                writer.write(b"+PONG\r\n")
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    found = core_valkey.client(_settings(valkey_url=SecretStr(f"valkey://127.0.0.1:{port}/0")))
    try:
        assert await found.ping() is True
        assert await found.ping() is True  # retried on a new connection
        assert connections == 2  # the first socket, then the reconnect
    finally:
        await found.aclose()
        server.close()
        await server.wait_closed()
