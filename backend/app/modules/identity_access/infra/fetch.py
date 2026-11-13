"""Fetch an identity provider's discovery document or SAML metadata (WP-039, D-094; WP-057 S1).

The address is typed by a tenant admin, so this is a server-side request forgery risk (as the
custom domain check, WP-017). Every call goes through the one guarded client (`app.shared.egress`,
ADR-043 §8): the host is resolved ONCE, every answer is checked, and the connection goes to the
checked address (a DNS answer that changes between check and connect is never used); no
redirects; five seconds to connect; at most 1 MB read.

Never contacted (audit #3): link-local (cloud metadata), multicast and unspecified addresses,
whatever the configuration says; private ranges, CGNAT and loopback unless the installation lists
them (`SUPPORTX_EGRESS_ALLOW`: an on-prem identity provider on a private network is listed there;
loopback only in the dev and test profiles, `sso_fetch_allow_loopback`, where the test identity
provider runs on the same machine). Any port: providers often listen on 8443, and the address
rules are what keep a call off internal services.
"""

import json
import uuid
from urllib.parse import urlencode

from app.shared.egress import Allowance, EgressError, OutboundRequest, send
from app.shared.egress.client import Resolver, system_resolver

MAX_BYTES = 1 << 20
MODULE = "identity_access"

INVALID, BLOCKED, UNREACHABLE = "invalid", "blocked", "unreachable"
_TOKEN_ANSWERS = frozenset({400, 401, 403})  # a refusal's body says whether the client was wrong


class FetchError(Exception):
    """The document could not be fetched (code for a translated message)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _fetch_error(error: EgressError) -> FetchError:
    if error.code == BLOCKED:
        return FetchError(BLOCKED)
    if error.code in {INVALID, "too_large"}:
        return FetchError(INVALID)
    return FetchError(UNREACHABLE)  # unreachable, timeout, tls, redirect, http_status


async def fetch_document(
    url: str,
    *,
    allowance: Allowance,
    tenant_id: uuid.UUID | None = None,
    resolver: Resolver = system_resolver,
) -> str:
    """The text at `url` (bounded), or FetchError("unreachable" | "blocked" | "invalid")."""
    request = OutboundRequest("GET", url, headers={"Accept": "application/json, application/xml"})
    try:
        response = await send(
            request,
            allowance=allowance.any_port(),
            module=MODULE,
            tenant_id=tenant_id,
            max_bytes=MAX_BYTES,
            resolver=resolver,
        )
    except EgressError as error:
        raise _fetch_error(error) from None
    if response.status != 200:  # noqa: PLR2004 - a document is only ever a 200
        raise FetchError(UNREACHABLE)
    return response.body.decode("utf-8", errors="replace")


async def client_accepted(
    token_url: str,
    client_id: str,
    client_secret: str,
    *,
    allowance: Allowance,
    tenant_id: uuid.UUID | None = None,
) -> bool:
    """Whether the provider accepts the client ID and secret (same address limits).

    A client-credentials request: providers check the client before the grant, so only a
    refusal of the client itself (`rejected`) means the ID or secret is wrong; any other answer
    (the grant not allowed, a missing scope) means they were accepted. Nothing is kept; the
    secret travels in the body, which the guarded client never logs.
    """
    body = urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
    ).encode()
    request = OutboundRequest(
        "POST",
        token_url,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        body=body,
    )
    try:
        response = await send(
            request,
            allowance=allowance.any_port(),
            module=MODULE,
            tenant_id=tenant_id,
            accept_statuses=_TOKEN_ANSWERS,
        )
    except EgressError as error:
        raise _fetch_error(error) from None
    try:
        answer = json.loads(response.body) if response.body else {}
    except ValueError:
        answer = {}
    if not isinstance(answer, dict):
        answer = {}
    return not rejected(response.status, answer)


def rejected(status: int, body: dict[str, object]) -> bool:
    """Whether a token endpoint's answer means the client ID or secret is wrong.

    The standard says `invalid_client` (Entra ID, Okta, Google). Keycloak as the customer's
    provider answers `unauthorized_client` both for a wrong secret and for a right one without
    client-credentials rights, telling them apart only in its description (proved on 26.8.1).
    A 401 with no error at all is taken as a refusal.
    """
    error = body.get("error")
    description = str(body.get("error_description") or "").lower()
    if error == "invalid_client" or "invalid client" in description:
        return True
    return status == 401 and error is None  # noqa: PLR2004 - Unauthorized
