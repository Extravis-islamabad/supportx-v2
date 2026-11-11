"""The one guarded outbound HTTP client (ADR-043 §8; lane B's constraints; WP-055 reuses it).

Every call a tenant can aim (a workflow's webhook node, outbound webhooks) goes through `send`:

- **Pinned at the connection.** The host is resolved once and every A/AAAA answer is checked
  (`addresses.allowed`); the connection then goes to the checked IP through an httpcore network
  backend, while TLS keeps SNI and verifies the certificate against the host name. A DNS answer
  that changes between check and connect (rebinding) is never used.
- **No redirects:** a 3xx is the result (`redirect`), never followed.
- **Limits:** 10 s in all, with connect and read limits under it; the response read up to a cap
  (1 MB unless the caller sets less); request body and header caps; no retries here (callers retry
  idempotently, from the outbox).
- **TLS:** always verified, TLS 1.2 at least; a destination may bring its own CA bundle and a
  client certificate for mTLS (the caller reads them from the secret store by reference).
- **Headers:** hop-by-hop headers and a `Host` override are refused; secret header values are
  never logged or returned in an error. The body is sent byte for byte (WP-055 signs it).
- **The egress record:** one structured log line per call with tenant, module, host, port, the
  status or error code, the duration and the bytes; never a body, query string or header.

Stable error codes: blocked, unreachable, timeout, too_large, tls, redirect, http_status, invalid,
insecure (secret headers over plain HTTP to a host the installation has not listed).
Not yet: an installation-level HTTPS proxy (`trust_env` stays off meanwhile); see PROGRESS.
"""

import asyncio
import os
import re
import socket
import ssl
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpcore
import structlog

from app.shared.egress.addresses import Allowance, IPAddress, allowed

log = structlog.get_logger("app.egress")

TOTAL_SECONDS = 10.0
CONNECT_SECONDS = 5.0
READ_SECONDS = 8.0
MAX_RESPONSE_BYTES = 1 << 20
MAX_BODY_BYTES = 1 << 20
MAX_HEADERS = 50
MAX_HEADER_BYTES = 8 << 10
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
)
BLOCKED, UNREACHABLE, TIMEOUT, TOO_LARGE = "blocked", "unreachable", "timeout", "too_large"
INSECURE = "insecure"
METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"})  # never CONNECT or TRACE
_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")  # an RFC 9110 field name
TLS, REDIRECT, HTTP_STATUS, INVALID = "tls", "redirect", "http_status", "invalid"

Resolver = Callable[[str, int], Awaitable[list[IPAddress]]]


class EgressError(Exception):
    """The call did not succeed; `code` is one of the stable codes (never a secret)."""

    def __init__(self, code: str, *, status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class Destination:
    """Per-destination TLS material, read by the caller from the secret store."""

    ca_pem: str | None = None  # trust this CA bundle instead of the system's
    client_cert_pem: str | None = None  # mTLS: certificate and key, both or neither
    client_key_pem: str | None = None


@dataclass(frozen=True)
class OutboundRequest:
    """One call: the method, address, headers (secret ones apart) and the exact body."""

    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    secret_headers: Mapping[str, str] = field(default_factory=dict)  # never logged or returned
    body: bytes = b""


@dataclass(frozen=True)
class OutboundResponse:
    """What came back: status, headers and the body (at most the cap)."""

    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


async def system_resolver(host: str, port: int) -> list[IPAddress]:
    """Every address the host resolves to, once."""
    import ipaddress  # noqa: PLC0415 - kept with the only resolver that needs it

    loop = asyncio.get_running_loop()
    try:
        found = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise EgressError(UNREACHABLE) from None
    return sorted({ipaddress.ip_address(str(info[4][0])) for info in found}, key=str)


class PinnedBackend(httpcore.AsyncNetworkBackend):
    """Connects to the checked IP whatever host httpcore asks for (TLS still uses the name)."""

    def __init__(self, ip: IPAddress, inner: httpcore.AsyncNetworkBackend | None = None) -> None:
        """Pinned to `ip`."""
        self.ip = ip
        self.inner = inner or httpcore.AnyIOBackend()
        self.connected: list[tuple[str, int]] = []

    async def connect_tcp(  # noqa: D102 - httpcore's interface
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore's interface
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        del host  # the name was resolved and checked once; never resolved again here
        self.connected.append((str(self.ip), port))
        return await self.inner.connect_tcp(
            str(self.ip),
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(  # noqa: D102 - httpcore's interface
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore's interface
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        del path, timeout, socket_options
        raise httpcore.ConnectError(BLOCKED)

    async def sleep(self, seconds: float) -> None:  # noqa: D102 - httpcore's interface
        await self.inner.sleep(seconds)


def _ssl_context(destination: Destination | None) -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    if destination is None:
        return context
    if destination.ca_pem:
        context = ssl.create_default_context(cadata=destination.ca_pem)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
    if destination.client_cert_pem and destination.client_key_pem:
        _load_client_cert(context, destination.client_cert_pem, destination.client_key_pem)
    return context


def _load_client_cert(context: ssl.SSLContext, cert: str, key: str) -> None:
    """The ssl module reads certificates from files only: a private temp file, removed at once."""
    handle, path = tempfile.mkstemp(prefix="sx-mtls-", suffix=".pem")
    try:
        with os.fdopen(handle, "w", encoding="ascii") as out:
            out.write(cert.strip() + "\n" + key.strip() + "\n")
        context.load_cert_chain(path)
    except (ssl.SSLError, ValueError):
        raise EgressError(TLS) from None
    finally:
        Path(path).unlink(missing_ok=True)


def _headers(request: OutboundRequest) -> list[tuple[bytes, bytes]]:
    merged = {**request.headers, **request.secret_headers}
    if len(merged) > MAX_HEADERS:
        raise EgressError(INVALID)
    out: list[tuple[bytes, bytes]] = []
    size = 0
    for name, value in merged.items():
        bad_value = any(c in value for c in "\r\n\x00")
        if name.lower() in _HOP_BY_HOP or not _TOKEN.fullmatch(name) or bad_value:
            raise EgressError(INVALID)
        size += len(name) + len(value)
        out.append((name.encode("ascii"), value.encode("utf-8")))
    if size > MAX_HEADER_BYTES:
        raise EgressError(INVALID)
    return out


def _target(request: OutboundRequest, allowance: Allowance) -> tuple[str, int]:
    """The host and port, or why the call is refused before any lookup (lane B's review)."""
    if request.method not in METHODS:
        raise EgressError(INVALID)
    parts = urlsplit(request.url)
    credentials = parts.username is not None or parts.password is not None
    if parts.scheme not in {"http", "https"} or not parts.hostname or credentials:
        raise EgressError(INVALID)
    host = parts.hostname.lower().rstrip(".")
    if request.secret_headers and parts.scheme == "http" and host not in allowance.hosts:
        raise EgressError(INSECURE)  # an API key never travels in clear (dev receivers: listed)
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise EgressError(INVALID) from None
    if port not in allowance.ports:
        raise EgressError(BLOCKED)
    return parts.hostname, port


async def send(  # noqa: PLR0913 - the call and everything that bounds it, explicit
    request: OutboundRequest,
    *,
    allowance: Allowance,
    module: str,
    tenant_id: uuid.UUID | None,
    destination: Destination | None = None,
    max_bytes: int = MAX_RESPONSE_BYTES,
    resolver: Resolver = system_resolver,
    backend: httpcore.AsyncNetworkBackend | None = None,
) -> OutboundResponse:
    """Make one guarded call; any 2xx is the response, anything else an `EgressError`."""
    started = time.monotonic()
    where = urlsplit(request.url)
    host = where.hostname or ""
    call = _Call(request, allowance, destination, min(max_bytes, MAX_RESPONSE_BYTES), backend)
    try:
        response = await asyncio.wait_for(call.run(resolver), timeout=TOTAL_SECONDS)
    except EgressError as error:
        _record(tenant_id, module, host, call.port, started, status=error.status, code=error.code)
        raise
    except TimeoutError:
        _record(tenant_id, module, host, call.port, started, code=TIMEOUT)
        raise EgressError(TIMEOUT) from None
    _record(
        tenant_id,
        module,
        host,
        call.port,
        started,
        status=response.status,
        received=len(response.body),
    )
    return response


@dataclass
class _Call:
    """One guarded call's parts."""

    request: OutboundRequest
    allowance: Allowance
    destination: Destination | None
    cap: int
    backend: httpcore.AsyncNetworkBackend | None
    port: int = 0

    async def run(self, resolver: Resolver) -> OutboundResponse:
        host, self.port = _target(self.request, self.allowance)
        if len(self.request.body) > MAX_BODY_BYTES:
            raise EgressError(TOO_LARGE)
        headers = _headers(self.request)
        ip = await _checked_address(host, self.port, self.allowance, resolver)
        response = await _call(self, ip, headers)
        _status(response.status)
        return response


def _status(status: int) -> None:
    if 300 <= status < 400:  # noqa: PLR2004 - the redirect range
        raise EgressError(REDIRECT, status=status)
    if not 200 <= status < 300:  # noqa: PLR2004 - the success range
        raise EgressError(HTTP_STATUS, status=status)


async def _checked_address(
    host: str, port: int, allowance: Allowance, resolver: Resolver
) -> IPAddress:
    """Resolve once; every answer must be allowed (one bad answer blocks the call)."""
    import ipaddress  # noqa: PLC0415 - a literal address needs no resolver

    try:
        answers: list[IPAddress] = [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        answers = await resolver(host, port)
    if not answers:
        raise EgressError(UNREACHABLE)
    if not all(allowed(ip, host, allowance) for ip in answers):
        raise EgressError(BLOCKED)
    return answers[0]


async def _call(call: _Call, ip: IPAddress, headers: list[tuple[bytes, bytes]]) -> OutboundResponse:
    request, destination, cap, backend = call.request, call.destination, call.cap, call.backend
    pool = httpcore.AsyncConnectionPool(
        ssl_context=_ssl_context(destination),
        network_backend=PinnedBackend(ip, backend),
        max_connections=1,
        retries=0,
        http2=False,
    )
    timeouts = {
        "connect": CONNECT_SECONDS,
        "read": READ_SECONDS,
        "write": READ_SECONDS,
        "pool": CONNECT_SECONDS,
    }
    try:
        async with (
            pool,
            pool.stream(
                request.method,
                request.url,
                headers=headers,
                content=request.body,
                extensions={"timeout": timeouts},
            ) as response,
        ):
            body = bytearray()
            async for chunk in response.aiter_stream():
                body += chunk
                if len(body) > cap:
                    raise EgressError(TOO_LARGE, status=response.status)
            pairs = tuple((k.decode("latin-1"), v.decode("latin-1")) for k, v in response.headers)
            return OutboundResponse(response.status, pairs, bytes(body))
    except (
        httpcore.ConnectTimeout,
        httpcore.ReadTimeout,
        httpcore.WriteTimeout,
        httpcore.PoolTimeout,
    ):
        raise EgressError(TIMEOUT) from None
    except httpcore.ConnectError as error:
        raise EgressError(TLS if _is_tls(error) else UNREACHABLE) from None
    except (httpcore.ProtocolError, httpcore.NetworkError, httpcore.UnsupportedProtocol):
        raise EgressError(UNREACHABLE) from None


def _is_tls(error: BaseException) -> bool:
    cause: BaseException | None = error
    while cause is not None:
        if isinstance(cause, ssl.SSLError):
            return True
        cause = cause.__cause__ or cause.__context__
    return "SSL" in str(error) or "certificate" in str(error).lower()


def _record(  # noqa: PLR0913 - one egress record's fields, explicit
    tenant_id: uuid.UUID | None,
    module: str,
    host: str,
    port: int,
    started: float,
    *,
    status: int | None = None,
    received: int = 0,
    code: str | None = None,
) -> None:
    """The egress record: never a body, a query string or a header (ADR-043 §8)."""
    log.info(
        "egress_call",
        tenant_id=str(tenant_id) if tenant_id else None,
        module=module,
        host=host,
        port=port,
        status=status,
        code=code,
        duration_ms=round((time.monotonic() - started) * 1000, 1),
        bytes=received,
    )
