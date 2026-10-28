"""Dependency probes for readiness: one short-lived connection and one trivial round trip each.

Each probe opens and closes its own connection on purpose: readiness must prove a *new*
connection works (credentials, network, pool), which a long-lived pooled connection would hide.
Library-specific errors are translated to stable FailureReason codes here, at the edge.
"""

import asyncio
import json
import math
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import asyncpg
import httpx
import nats
import nats.errors
import nats.js.errors
import valkey.asyncio
import valkey.exceptions
from nats.aio.client import Client as NatsClient

from app.modules.system.domain.readiness import FailureReason, ProbeFailedError


class PostgresProbe:
    """`SELECT 1` as the application role (through PgBouncer in the dev stack)."""

    name = "postgres"

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def check(self, timeout_s: float) -> None:
        """Connect, run `SELECT 1`, disconnect."""
        try:
            connection = await asyncpg.connect(
                self._dsn, timeout=timeout_s, command_timeout=timeout_s
            )
        except asyncpg.InvalidAuthorizationSpecificationError as exc:
            raise ProbeFailedError(FailureReason.AUTH_FAILED) from exc
        except asyncpg.ProtocolViolationError as exc:
            # PgBouncer reports a failed SCRAM login as a protocol violation (SQLSTATE 08P01,
            # "SASL authentication failed") rather than PostgreSQL's 28P01.
            if "authentication" in str(exc).lower():
                raise ProbeFailedError(FailureReason.AUTH_FAILED) from exc
            raise
        try:
            if await connection.fetchval("SELECT 1") != 1:
                raise ProbeFailedError(FailureReason.UNEXPECTED_RESPONSE)
        finally:
            await connection.close(timeout=timeout_s)


class ValkeyProbe:
    """`PING` with the configured credentials."""

    name = "valkey"

    def __init__(self, url: str) -> None:
        self._url = url

    async def check(self, timeout_s: float) -> None:
        """Connect, PING, disconnect."""
        # valkey-py ships no annotations for from_url; the return type is declared here.
        client: valkey.asyncio.Valkey = valkey.asyncio.from_url(  # type: ignore[no-untyped-call]
            self._url, socket_connect_timeout=timeout_s, socket_timeout=timeout_s
        )
        try:
            if await client.ping() is not True:
                raise ProbeFailedError(FailureReason.UNEXPECTED_RESPONSE)
        except valkey.exceptions.AuthenticationError as exc:
            raise ProbeFailedError(FailureReason.AUTH_FAILED) from exc
        except valkey.exceptions.TimeoutError as exc:
            raise ProbeFailedError(FailureReason.TIMEOUT) from exc
        except valkey.exceptions.ConnectionError as exc:
            raise ProbeFailedError(FailureReason.UNREACHABLE) from exc
        finally:
            await client.aclose()


NATS_DEFAULT_PORT = 4222


async def _ignore_nats_error(_error: Exception) -> None:
    """nats-py logs every connection error by default; the probe reports its own reason."""


async def _connect_nats(url: str, timeout_s: float) -> NatsClient:
    """One short-lived NATS connection that fails fast instead of retrying."""
    # nats-py keeps retrying a refused initial connection instead of failing fast, which would
    # turn "unreachable" into a timeout; a plain TCP connect answers that first.
    parts = urlsplit(url)
    _reader, writer = await asyncio.wait_for(
        asyncio.open_connection(parts.hostname, parts.port or NATS_DEFAULT_PORT), timeout_s
    )
    writer.close()
    await writer.wait_closed()
    try:
        return await nats.connect(
            url,
            connect_timeout=timeout_s,
            allow_reconnect=False,
            max_reconnect_attempts=0,
            error_cb=_ignore_nats_error,
        )
    except (nats.errors.AuthorizationError, nats.errors.InvalidUserCredentialsError) as exc:
        raise ProbeFailedError(FailureReason.AUTH_FAILED) from exc
    except nats.errors.NoServersError as exc:
        raise ProbeFailedError(FailureReason.UNREACHABLE) from exc


class NatsProbe:
    """Connect to NATS (server INFO + CONNECT handshake) and flush one round trip."""

    name = "nats"

    def __init__(self, url: str) -> None:
        self._url = url

    async def check(self, timeout_s: float) -> None:
        """Connect without reconnecting, flush, close."""
        client = await _connect_nats(self._url, timeout_s)
        try:
            # nats-py takes whole seconds here.
            await client.flush(timeout=max(1, math.ceil(timeout_s)))
        finally:
            await client.close()


class WorkerHeartbeatProbe:
    """Is at least one worker of a kind alive? Reads its heartbeat from the NATS KV bucket.

    Read-only: this never publishes. The workers write `<kind>.<instance>` every few seconds
    (workers/heartbeat.py); a key expires a minute after its worker stops.
    """

    def __init__(  # noqa: PLR0913 - keyword-only probe settings
        self,
        url: str,
        *,
        name: str,
        bucket: str,
        kind: str,
        stale_after_s: float,
        backlog_after_s: float | None = None,
    ) -> None:
        self.name = name
        self._url = url
        self._bucket = bucket
        self._prefix = f"{kind}."
        self._stale_after_s = stale_after_s
        self._backlog_after_s = backlog_after_s

    async def check(self, timeout_s: float) -> None:
        """Fails with not_running, stale_heartbeat, disconnected or backlog (delivery stalled).

        `disconnected`: the newest heartbeat says the worker cannot reach PostgreSQL or NATS now
        (workers/resilience.py). `backlog` (relay): its oldest unpublished event is too old.
        """
        client = await _connect_nats(self._url, timeout_s)
        try:
            newest = await self._newest_heartbeat(client)
        finally:
            await client.close()
        if newest is None:
            raise ProbeFailedError(FailureReason.NOT_RUNNING)
        at, stats = newest
        if (datetime.now(UTC) - at).total_seconds() > self._stale_after_s:
            raise ProbeFailedError(FailureReason.STALE_HEARTBEAT)
        if stats.get("connected") is False:
            raise ProbeFailedError(FailureReason.DISCONNECTED)
        age = stats.get("oldest_unpublished_age_seconds")
        limit = self._backlog_after_s
        if limit is not None and isinstance(age, (int, float)) and age > limit:
            raise ProbeFailedError(FailureReason.BACKLOG)

    async def _newest_heartbeat(self, client: NatsClient) -> tuple[datetime, dict[str, Any]] | None:
        try:
            bucket = await client.jetstream().key_value(self._bucket)
            keys = await bucket.keys()
        except (nats.js.errors.BucketNotFoundError, nats.js.errors.NoKeysError):
            return None
        newest: tuple[datetime, dict[str, Any]] | None = None
        for key in keys:
            if not key.startswith(self._prefix):
                continue
            try:
                entry = await bucket.get(key)
            except nats.js.errors.KeyNotFoundError:
                continue  # expired between keys() and get()
            if entry.value:
                document = json.loads(entry.value)
                at = datetime.fromisoformat(document["at"])
                if newest is None or at > newest[0]:
                    newest = (at, dict(document.get("stats") or {}))
        return newest


class KeycloakProbe:
    """The realm's OIDC discovery document answers (login depends on it)."""

    name = "keycloak"

    def __init__(self, issuer: str) -> None:
        self._url = issuer.rstrip("/") + "/.well-known/openid-configuration"

    async def check(self, timeout_s: float) -> None:
        """GET the discovery document."""
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.get(self._url)
        except httpx.TimeoutException as exc:
            raise ProbeFailedError(FailureReason.TIMEOUT) from exc
        except httpx.HTTPError as exc:
            raise ProbeFailedError(FailureReason.UNREACHABLE) from exc
        if response.status_code != 200 or "issuer" not in response.text:  # noqa: PLR2004 - HTTP OK
            raise ProbeFailedError(FailureReason.UNEXPECTED_RESPONSE)
