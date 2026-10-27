"""Fetch an identity provider's discovery document or SAML metadata (WP-039, D-094).

The address is typed by a tenant admin, so this is a server-side request forgery risk (as the
custom domain check, WP-017). Limits: the host must resolve, and to no link-local (cloud
metadata), multicast, unspecified or reserved address, nor loopback unless the installation
allows it (`sso_fetch_allow_loopback`, dev and CI only: their test identity provider runs on
the same machine); no redirects; five seconds; at most 1 MB read. Private networks are allowed
(on-prem identity providers live there).
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

TIMEOUT_SECONDS = 5.0
MAX_BYTES = 1 << 20


INVALID, BLOCKED, UNREACHABLE = "invalid", "blocked", "unreachable"


class FetchError(Exception):
    """The document could not be fetched (code for a translated message)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def blocked(address: str, *, allow_loopback: bool) -> bool:
    """Addresses never contacted on a tenant admin's behalf."""
    ip = ipaddress.ip_address(address)
    if ip.is_loopback:
        return not allow_loopback
    return ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved


async def _addresses(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        found = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise FetchError(UNREACHABLE) from None
    return sorted({str(info[4][0]) for info in found})


async def fetch_document(
    url: str,
    *,
    allow_loopback: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """The text at `url` (bounded), or FetchError("unreachable" | "blocked" | "invalid")."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError(INVALID)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    addresses = await _addresses(parts.hostname, port)
    if not addresses or any(blocked(a, allow_loopback=allow_loopback) for a in addresses):
        raise FetchError(BLOCKED)
    try:
        async with (
            httpx.AsyncClient(
                timeout=TIMEOUT_SECONDS, follow_redirects=False, transport=transport
            ) as client,
            client.stream(
                "GET", url, headers={"Accept": "application/json, application/xml"}
            ) as response,
        ):
            if response.status_code != httpx.codes.OK:
                raise FetchError(UNREACHABLE)
            body = b""
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise FetchError(INVALID)
    except httpx.HTTPError:
        raise FetchError(UNREACHABLE) from None
    return body.decode("utf-8", errors="replace")


async def client_accepted(
    token_url: str,
    client_id: str,
    client_secret: str,
    *,
    allow_loopback: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bool:
    """Whether the provider accepts the client ID and secret (same address limits).

    A client-credentials request: providers check the client before the grant, so only
    `invalid_client` (or 401) means the ID or secret is wrong; any other answer (the grant not
    allowed, a missing scope) means they were accepted. Nothing is kept from the answer.
    """
    parts = urlsplit(token_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError(INVALID)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    addresses = await _addresses(parts.hostname, port)
    if not addresses or any(blocked(a, allow_loopback=allow_loopback) for a in addresses):
        raise FetchError(BLOCKED)
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=False, transport=transport
        ) as client:
            response = await client.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )
    except httpx.HTTPError:
        raise FetchError(UNREACHABLE) from None
    if response.status_code == httpx.codes.UNAUTHORIZED:
        return False
    try:
        error = response.json().get("error") if response.content else None
    except ValueError:
        error = None
    return error != "invalid_client"
