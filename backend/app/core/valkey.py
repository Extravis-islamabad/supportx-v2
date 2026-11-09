"""One way to reach Valkey: a single server, or the master Sentinel names (WP-014b, D-038).

Every Valkey client in the app and the workers comes from `client()`. With
`SUPPORTX_VALKEY_SENTINELS` set, it asks the sentinels for the current master of
`SUPPORTX_VALKEY_SENTINEL_MASTER` and follows a failover by itself. Without it, it's exactly
`valkey.asyncio.from_url(valkey_url)`. Configuration decides, never the deployment mode
(CLAUDE.md rule 5f).

Every client retries a command that lost its connection a few times with a short backoff (about
a second in all). In a failover the pooled connections still point at the old master: the first
command on each fails once (valkey-py's Sentinel connection turns the demoted master's READONLY
into a ConnectionError and drops the socket), and the retry reconnects to the master the sentinels
name now. Past the retry, the API answers 503 with Retry-After (app/core/errors.py), never a
bare 500. A caller may pass its own `retry`; the readiness probe passes none, as it must report
what it sees at once.

A retried command can run twice when only its reply was lost. Every command the app sends that
is not naturally idempotent (audit 2026-11-09; workers/ use NATS KV, not Valkey), and why a
second run is safe:
- GET, MGET: reads.
- SET with PX (sessions, pending logins, SSO tests, ended-at marks, policy and licence caches)
  and DEL: the same value again, or nothing left to delete.
- INCR of a cache generation (identity_access policy, licensing cache): one extra bump only
  makes the next read miss the cache once and reload it.
- INCR + PEXPIRE NX in MULTI (`SessionStore.hit`, password-reset limits) and the rate limiter's
  Lua INCRs (app/shared/api/ratelimit.py): one extra count, so a limit errs strict by one
  request in that window; no limit is ever loosened.
- HSET + PEXPIRE NX + PEXPIRE GT in MULTI, HGETALL and HDEL of a person's session index
  (`SessionStore`, the signed-in devices, ADR-044): the same field and value again, or a field
  already gone.
- GETDEL of a pending sign-in (`take_login`): the second run finds it gone, so that sign-in
  ends as "expired, start again". It can never be used twice (fails safe, never open).
- The token-refresh lock (`SessionStore.lock`): SET NX with a per-attempt token; a retry that
  finds the key holding its own token knows the first try won. Release is a compare-and-delete
  script, so it never frees another holder's lock and a second run does nothing.
No LPUSH/RPUSH/XADD/SADD and no PUBLISH go to Valkey (realtime publishes go to Centrifugo).
A new non-idempotent command needs its line here, or a token as the lock has.
"""

from typing import Any

import valkey.asyncio
import valkey.exceptions
from valkey.asyncio.connection import SSLConnection, parse_url
from valkey.asyncio.retry import Retry
from valkey.asyncio.sentinel import Sentinel
from valkey.backoff import ExponentialBackoff

from app.core.config import Settings

RETRIES = 3
RETRY_ERRORS = [valkey.exceptions.ConnectionError, valkey.exceptions.TimeoutError]


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


def bounded_retry() -> Retry:
    """3 retries, 50 ms doubling up to 500 ms: rides out a failover's dropped connections."""
    return Retry(ExponentialBackoff(cap=0.5, base=0.05), RETRIES)


def client(settings: Settings, **options: Any) -> valkey.asyncio.Valkey:  # noqa: ANN401 - valkey-py's connection options
    """A Valkey client for this installation (caller closes it with `aclose()`)."""
    if settings.valkey_url is None:
        raise ValkeyNotConfiguredError
    options.setdefault("retry", bounded_retry())
    options.setdefault("retry_on_error", list(RETRY_ERRORS))
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
