"""One Valkey client factory: a single server, or the master Sentinel names (WP-014b)."""

import pytest
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
