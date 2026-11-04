"""One way to reach Valkey: a single server, or the master Sentinel names (WP-014b, D-038).

Every Valkey client in the app and the workers comes from `client()`. With
`SUPPORTX_VALKEY_SENTINELS` set, it asks the sentinels for the current master of
`SUPPORTX_VALKEY_SENTINEL_MASTER` and follows a failover by itself. Without it, it's exactly
`valkey.asyncio.from_url(valkey_url)`. Configuration decides, never the deployment mode
(CLAUDE.md rule 5f).
"""

from typing import Any

import valkey.asyncio
from valkey.asyncio.connection import SSLConnection, parse_url
from valkey.asyncio.sentinel import Sentinel

from app.core.config import Settings


class ValkeyNotConfiguredError(RuntimeError):
    """`client()` was asked for Valkey where `SUPPORTX_VALKEY_URL` is not set."""


def sentinel_hosts(value: str) -> list[tuple[str, int]]:
    """`"a:26379,b:26379"` as (host, port) pairs; the port defaults to Sentinel's 26379."""
    found: list[tuple[str, int]] = []
    for item in (part.strip() for part in value.split(",")):
        if not item:
            continue
        host, _, port = item.rpartition(":") if ":" in item else (item, "", "26379")
        if not host or not port.isdigit():
            msg = f"SUPPORTX_VALKEY_SENTINELS: {item!r} is not host:port"
            raise ValueError(msg)
        found.append((host, int(port)))
    if not found:
        msg = "SUPPORTX_VALKEY_SENTINELS names no sentinel"
        raise ValueError(msg)
    return found


def client(settings: Settings, **options: Any) -> valkey.asyncio.Valkey:  # noqa: ANN401 - valkey-py's connection options
    """A Valkey client for this installation (caller closes it with `aclose()`)."""
    if settings.valkey_url is None:
        raise ValkeyNotConfiguredError
    url = settings.valkey_url.get_secret_value()
    if not settings.valkey_sentinels:
        found: valkey.asyncio.Valkey = valkey.asyncio.from_url(url, **options)  # type: ignore[no-untyped-call]  # valkey-py ships no annotation for from_url
        return found
    data = parse_url(url)
    data.pop("host", None)
    data.pop("port", None)
    if data.pop("connection_class", None) is SSLConnection:
        data["ssl"] = True  # Sentinel's pool picks its own TLS connection class from this
    password = settings.valkey_sentinel_password
    sentinel = Sentinel(  # type: ignore[no-untyped-call]  # valkey-py ships no annotation for Sentinel
        sentinel_hosts(settings.valkey_sentinels),
        sentinel_kwargs={
            "password": password.get_secret_value() if password else data.get("password"),
            **({"ssl": True} if data.get("ssl") else {}),
            **{k: v for k, v in options.items() if k.startswith("socket_")},
        },
        **data,
        **options,
    )
    master: valkey.asyncio.Valkey = sentinel.master_for(settings.valkey_sentinel_master)
    return master
