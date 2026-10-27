"""Fetch a custom domain's proof token (WP-017; the rule is in domain/domains.py).

A request the server makes to an address a tenant typed is a server-side request forgery risk.
Limits: the host must resolve, and to no loopback, link-local (cloud metadata), multicast or
reserved address; plain HTTP on port 80 to one fixed path; no redirects; five seconds; at most
256 bytes read; the answer is only compared, never shown or stored. Private networks are allowed
(on-prem custom domains resolve to them).
"""

from __future__ import annotations

import asyncio
import socket

import httpx

from app.modules.organization.domain.domains import CHECK_PATH, blocked_address

TIMEOUT_SECONDS = 5.0
MAX_ANSWER = 256


class DomainCheckError(Exception):
    """The address could not be checked (code for a translated message)."""

    def __init__(self, *, code: str) -> None:
        super().__init__(code)
        self.code = code


async def _addresses(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        found = await loop.getaddrinfo(host, 80, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise DomainCheckError(code="domain_not_resolving") from None
    return sorted({str(info[4][0]) for info in found})


async def fetch_answer(
    host: str, token: str, transport: httpx.AsyncBaseTransport | None = None
) -> str:
    """The body `http://<host>/api/v1/public/domain-check/<token>` answers (bounded)."""
    addresses = await _addresses(host)
    if not addresses or any(blocked_address(address) for address in addresses):
        raise DomainCheckError(code="domain_address_not_allowed")
    url = f"http://{host}{CHECK_PATH}{token}"
    try:
        async with (
            httpx.AsyncClient(
                timeout=TIMEOUT_SECONDS, follow_redirects=False, transport=transport
            ) as client,
            client.stream("GET", url) as response,
        ):
            if response.status_code != 200:  # noqa: PLR2004 - HTTP OK
                raise DomainCheckError(code="domain_check_failed")
            body = b""
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > MAX_ANSWER:
                    raise DomainCheckError(code="domain_check_failed")
    except httpx.HTTPError:
        raise DomainCheckError(code="domain_not_reachable") from None
    return body.decode("ascii", errors="replace")
