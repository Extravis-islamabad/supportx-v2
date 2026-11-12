"""Dependency probes for readiness: one short-lived connection and one trivial round trip each.

Each probe opens and closes its own connection on purpose: readiness must prove a *new*
connection works (credentials, network, pool), which a long-lived pooled connection would hide.
Library-specific errors are translated to stable FailureReason codes here, at the edge.
"""

import asyncio
import json
import math
import time
from datetime import UTC, datetime, timedelta
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
from opentelemetry import metrics

from app.core.config import Settings
from app.core.valkey import client as valkey_client
from app.modules.system.domain.readiness import FailureReason, ProbeFailedError
from app.shared.files.infra.scanner import Scanner, ScannerUnavailableError


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

    def __init__(self, url: str, settings: Settings | None = None) -> None:
        self._url = url
        self._settings = settings  # with sentinels configured: the master they name (WP-014b)

    async def check(self, timeout_s: float) -> None:
        """Connect, PING, disconnect."""
        timeouts = {"socket_connect_timeout": timeout_s, "socket_timeout": timeout_s}
        client: valkey.asyncio.Valkey
        if self._settings is not None and self._settings.valkey_sentinels:
            # One try: a probe reports what it sees now, without the app's bounded retry.
            client = valkey_client(self._settings, retry=None, retry_on_error=[], **timeouts)
        else:
            # valkey-py ships no annotations for from_url; the return type is declared here.
            client = valkey.asyncio.from_url(self._url, **timeouts)  # type: ignore[no-untyped-call]
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
        js = client.jetstream()
        try:
            bucket = await js.key_value(self._bucket)
            # The keys from the stream's own subject list, not `bucket.keys()`: its watcher can
            # report "no keys" when it reads the consumer before the first message is counted
            # (nats-py), which made a running worker look stopped (CI, 2026-10-28).
            info = await js.stream_info(
                f"KV_{self._bucket}", subjects_filter=f"$KV.{self._bucket}.{self._prefix}>"
            )
        except nats.js.errors.NotFoundError:  # no bucket yet (BucketNotFoundError) or no stream
            return None
        subjects = (info.state.subjects or {}) if info.state else {}
        keys = [subject.removeprefix(f"$KV.{self._bucket}.") for subject in subjects]
        newest: tuple[datetime, dict[str, Any]] | None = None
        for key in keys:
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


_signature_age = metrics.get_meter("supportx.files").create_gauge(
    "supportx_files_signature_age_seconds",
    unit="s",
    description="Age of ClamAV's virus signatures, as clamd reports them (WP-014b).",
)


class SessionKeysProbe:
    """Informational: more sign-in keys listed than one overlap needs (D-162, ADR-048).

    Old keys that are never retired keep every one of them able to open sessions. A warning in
    /ready, never unready: sessions work either way. No I/O: the count is the settings'.
    """

    name = "session_keys"

    def __init__(self, listed: int, *, most: int) -> None:
        self._listed = listed
        self._most = most

    async def check(self, timeout_s: float) -> None:
        """Raise ProbeFailedError(TOO_MANY_KEYS) above `most` listed keys."""
        del timeout_s
        if self._listed > self._most:
            raise ProbeFailedError(FailureReason.TOO_MANY_KEYS)


class MalwareSignaturesProbe:
    """Informational: are ClamAV's virus signatures fresh? Also records their age as a gauge.

    Stale signatures mean freshclam can't reach its mirror (with the egress allow-list on and no
    mirror or proxy listed, for instance). Files then wait for a scan, so it shows in /ready as
    a warning, not as unready. clamd is asked at most once a minute: /ready runs every few seconds.
    """

    name = "malware_signatures"

    def __init__(
        self, scanner: Scanner, *, stale_after: timedelta, cache_seconds: float = 60.0
    ) -> None:
        self._scanner = scanner
        self._stale_after = stale_after
        self._cache_seconds = cache_seconds
        self._checked_at: float | None = None
        self._failure: FailureReason | None = None

    async def check(self, timeout_s: float) -> None:
        """Raise ProbeFailedError(STALE_SIGNATURES or UNREACHABLE); the answer is cached."""
        now = time.monotonic()
        if self._checked_at is None or now - self._checked_at >= self._cache_seconds:
            self._failure = await self._ask(timeout_s)
            self._checked_at = now
        if self._failure is not None:
            raise ProbeFailedError(self._failure)

    async def _ask(self, timeout_s: float) -> FailureReason | None:
        try:
            version = await asyncio.wait_for(self._scanner.version(), timeout_s)
        except (ScannerUnavailableError, TimeoutError):
            return FailureReason.UNREACHABLE
        if version.signature_date is None:
            return None  # an engine that doesn't say: nothing to judge
        age = datetime.now(UTC) - version.signature_date
        _signature_age.set(age.total_seconds())
        return FailureReason.STALE_SIGNATURES if age > self._stale_after else None
