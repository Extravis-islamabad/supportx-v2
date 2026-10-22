"""Dependency probes for readiness: one short-lived connection and one trivial round trip each.

Each probe opens and closes its own connection on purpose: readiness must prove a *new*
connection works (credentials, network, pool), which a long-lived pooled connection would hide.
Library-specific errors are translated to stable FailureReason codes here, at the edge.
"""

import asyncio
import math
from urllib.parse import urlsplit

import asyncpg
import httpx
import nats
import nats.errors
import valkey.asyncio
import valkey.exceptions

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


class NatsProbe:
    """Connect to NATS (server INFO + CONNECT handshake) and flush one round trip."""

    name = "nats"

    def __init__(self, url: str) -> None:
        self._url = url

    async def check(self, timeout_s: float) -> None:
        """Connect without reconnecting, flush, close."""
        await self._require_tcp(timeout_s)
        try:
            client = await nats.connect(
                self._url,
                connect_timeout=timeout_s,
                allow_reconnect=False,
                max_reconnect_attempts=0,
                error_cb=_ignore_nats_error,
            )
        except (nats.errors.AuthorizationError, nats.errors.InvalidUserCredentialsError) as exc:
            raise ProbeFailedError(FailureReason.AUTH_FAILED) from exc
        except nats.errors.NoServersError as exc:
            raise ProbeFailedError(FailureReason.UNREACHABLE) from exc
        try:
            # nats-py takes whole seconds here.
            await client.flush(timeout=max(1, math.ceil(timeout_s)))
        finally:
            await client.close()

    async def _require_tcp(self, timeout_s: float) -> None:
        # nats-py keeps retrying a refused initial connection instead of failing fast, which
        # would turn "unreachable" into a timeout; a plain TCP connect answers that first.
        url = urlsplit(self._url)
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(url.hostname, url.port or NATS_DEFAULT_PORT), timeout_s
        )
        writer.close()
        await writer.wait_closed()


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
