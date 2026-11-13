"""One Valkey client factory: a single server, or the master Sentinel names (WP-014b)."""

import asyncio
import ssl
from pathlib import Path
from typing import Any

import pytest
import valkey.exceptions
from pydantic import SecretStr
from valkey.asyncio.sentinel import SentinelConnectionPool

from app.core import valkey as core_valkey
from app.core.config import Settings
from tests.tls_certs import make_certs


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


# TLS (audit row 5): the CA reaches every connection, servers and sentinels alike.
@pytest.fixture
def ca(tmp_path: Path) -> str:
    return str(make_certs(tmp_path, ["cache"]).ca)


def test_a_ca_with_a_plaintext_url_is_refused_at_start(ca: str) -> None:
    with pytest.raises(ValueError, match="valkeys://"):
        Settings.load(
            env_file=None,
            profile="test",
            valkey_url=SecretStr("valkey://:pw@cache:6379/0"),
            valkey_tls_ca_file=ca,
        )
    found = Settings.load(
        env_file=None,
        profile="test",
        valkey_url=SecretStr("valkeys://:pw@cache:6379/0"),
        valkey_tls_ca_file=ca,
    )
    assert str(found.valkey_tls_ca_file) == ca


def _verified(kwargs: dict[str, Any], ca: str) -> bool:  # Any: valkey kwargs
    return (
        kwargs.get("ssl_ca_certs") == ca
        and kwargs.get("ssl_cert_reqs") == "required"
        and kwargs.get("ssl_check_hostname") is True
    )


async def test_tls_to_a_single_server_checks_the_ca_and_host_name(ca: str) -> None:
    found = core_valkey.client(
        _settings(valkey_url=SecretStr("valkeys://:pw@cache:6379/0"), valkey_tls_ca_file=Path(ca))
    )
    pool = found.connection_pool
    assert pool.connection_class.__name__ == "SSLConnection"
    assert _verified(pool.connection_kwargs, ca)
    connection = pool.make_connection()  # type: ignore[no-untyped-call]  # valkey-py ships no annotation
    context = connection.ssl_context.get()
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    await found.aclose()


async def test_tls_through_sentinels_checks_both_the_sentinels_and_the_master(ca: str) -> None:
    found = core_valkey.client(
        _settings(
            valkey_url=SecretStr("valkeys://:pw@ignored:6379/0"),
            valkey_sentinels="s1:26379,s2:26379",
            valkey_tls_ca_file=Path(ca),
        )
    )
    pool = found.connection_pool
    assert isinstance(pool, SentinelConnectionPool)
    assert pool.connection_class.__name__ == "SentinelManagedSSLConnection"
    assert _verified(pool.connection_kwargs, ca)
    for sentinel in pool.sentinel_manager.sentinels:
        assert sentinel.connection_pool.connection_class.__name__ == "SSLConnection"
        assert _verified(sentinel.connection_pool.connection_kwargs, ca)
    await found.aclose()


async def test_a_server_whose_certificate_names_another_host_is_refused(tmp_path: Path) -> None:
    """A real handshake on loopback: the right CA but the wrong name fails, the right one works."""
    certs = make_certs(tmp_path, ["localhost"])
    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_context.load_cert_chain(certs.cert, certs.key)

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while data := await reader.read(4096):
            writer.write(b"+OK\r\n" * data.upper().count(b"SETINFO"))
            if b"PING" in data.upper():
                writer.write(b"+PONG\r\n")
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(serve, "127.0.0.1", 0, ssl=server_context)
    port = server.sockets[0].getsockname()[1]
    try:
        for host, works in (("localhost", True), ("127.0.0.1", False)):
            found = core_valkey.client(
                _settings(
                    valkey_url=SecretStr(f"valkeys://{host}:{port}/0"),
                    valkey_tls_ca_file=certs.ca,
                ),
                retry=None,
                retry_on_error=[],
            )
            try:
                if works:
                    assert await found.ping() is True
                else:
                    with pytest.raises(valkey.exceptions.ConnectionError):
                        await found.ping()
            finally:
                await found.aclose()
    finally:
        server.close()
        await server.wait_closed()


async def test_without_a_ca_nothing_changes() -> None:
    found = core_valkey.client(_settings(valkey_url=SecretStr("valkey://cache:6379/0")))
    assert "ssl_ca_certs" not in found.connection_pool.connection_kwargs
    await found.aclose()
