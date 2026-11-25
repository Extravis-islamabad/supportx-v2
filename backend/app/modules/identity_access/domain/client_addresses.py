"""Which tenant addresses the console and portal clients accept as sign-in callbacks (ADR-031).

A sign-in started on a tenant's own address keeps its callback there (ADR-031 §4), so Keycloak
must know `<scheme>://<host>[:<port>]/api/v1/auth/callback` for every such host, on both clients,
and the host's origin as a web origin. Keycloak can't wildcard a host, so each one is registered:
the tenant's subdomain (`<slug>.<tenant_base_domain>`) and each verified custom domain. An
unverified domain is never registered; the address only hints where to sign in, never grants
access (ADR-031 §4).

The scheme and port come from the client's own base URL (`console_url`, `portal_url`), exactly as
the sign-in builds its callback (`AuthService.origin`: the configured scheme, the request's host).

**Managed entries.** SupportX manages only entries of its own shape: the callback path on a host
with the client's scheme and port, and that host's bare origin. The installation's shared
addresses (the clients' own base URLs, the mobile return address) are never managed, so never
removed; an entry of any other shape (added by hand by an operator) is left alone. Pure: no I/O.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

CALLBACK_PATH = "/api/v1/auth/callback"  # as identity_access/service/auth.py CALLBACK_PATH
_MAX_HOST = 253  # DNS


@dataclass(frozen=True)
class ClientBase:
    """One OIDC client and the base URL of the UI it signs in to."""

    client_id: str
    base_url: str

    @property
    def scheme(self) -> str:
        """The configured scheme (http only for local dev and tests)."""
        return urlsplit(self.base_url).scheme

    @property
    def port(self) -> int | None:
        """The configured port, kept on every tenant host (None: the scheme's default)."""
        return urlsplit(self.base_url).port

    @property
    def shared_host(self) -> str:
        """The installation's own host for this UI: never a managed entry."""
        return (urlsplit(self.base_url).hostname or "").lower()

    def origin(self, host: str) -> str:
        """`scheme://host[:port]` for a host of this client."""
        return f"{self.scheme}://{host}" + (f":{self.port}" if self.port else "")

    def callback(self, host: str) -> str:
        """The sign-in callback on a host of this client."""
        return self.origin(host) + CALLBACK_PATH


@dataclass(frozen=True)
class Addresses:
    """A client's redirect URIs and web origins."""

    redirect_uris: frozenset[str] = frozenset()
    web_origins: frozenset[str] = frozenset()

    def __bool__(self) -> bool:
        """Whether there is anything at all."""
        return bool(self.redirect_uris or self.web_origins)


@dataclass(frozen=True)
class Change:
    """What one client must gain and lose."""

    client_id: str
    add: Addresses
    remove: Addresses

    def __bool__(self) -> bool:
        """Whether anything changes."""
        return bool(self.add or self.remove)


_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def normalise_host(value: str) -> str | None:
    """A host in the form Keycloak compares: lower case, no trailing dot, IDN as punycode.

    None for anything that isn't a plain host name (a port, a path, an IP literal, an empty label).
    """
    host = value.strip().rstrip(".")
    if not host or any(c in host for c in "/:@[]?#\\ "):
        return None
    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    labels = ascii_host.split(".")
    if len(ascii_host) > _MAX_HOST or len(labels) < 2 or not all(labels):  # noqa: PLR2004 - a dot
        return None
    if all(label.isdigit() for label in labels):  # an IPv4 literal never names a tenant
        return None
    # Each label is letters, digits and hyphens, not starting or ending with one (RFC 1123, the
    # rule organization's domains use): this builds redirect URIs, so nothing else gets in, even
    # if a source ever let it through (lane C on #579).
    if not all(_LABEL.fullmatch(label) for label in labels):
        return None
    return ascii_host


def tenant_hosts(slug: str, base_domain: str | None, verified: Iterable[str]) -> frozenset[str]:
    """A tenant's hosts: its subdomain (with a base domain) and its verified custom domains.

    The caller passes verified domains only.
    """
    found: set[str] = set()
    if base_domain and slug and (host := normalise_host(f"{slug}.{base_domain}")) is not None:
        found.add(host)
    for raw in verified:
        if (host := normalise_host(raw)) is not None:
            found.add(host)
    return frozenset(found)


def wanted(client: ClientBase, hosts: Iterable[str]) -> Addresses:
    """The callbacks and origins `hosts` need on `client` (never the shared host itself)."""
    own = {h for h in hosts if h != client.shared_host}
    return Addresses(
        redirect_uris=frozenset(client.callback(h) for h in own),
        web_origins=frozenset(client.origin(h) for h in own),
    )


def managed_host(client: ClientBase, entry: str) -> str | None:
    """The host of an entry SupportX manages on `client`, else None (never the shared host).

    Managed: exactly `client.callback(host)` or `client.origin(host)` for a plain host name, with
    the client's scheme and port. Anything else (another path, a wildcard, another scheme or
    port, the shared host) is an operator's and is never touched.
    """
    parts = urlsplit(entry)
    if parts.scheme != client.scheme or parts.query or parts.fragment or "*" in entry:
        return None
    if parts.path not in ("", CALLBACK_PATH) or parts.username or parts.password:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    host = normalise_host(parts.hostname or "")
    if host is None or host == client.shared_host or port != client.port:
        return None
    # The exact shape only: a bare origin, or the callback (no trailing slash variants).
    if entry not in (client.origin(host), client.callback(host)):
        return None
    return host


def change(
    client: ClientBase,
    current: Addresses,
    want: Addresses,
    *,
    removable: frozenset[str] | None = None,
) -> Change:
    """What `client` must gain (what is wanted and missing) and lose.

    Lost: managed entries not wanted. `removable` limits removal to those hosts (one event's own
    domain); None (the reconcile) allows any managed host that nobody wants.
    """
    add = Addresses(
        redirect_uris=want.redirect_uris - current.redirect_uris,
        web_origins=want.web_origins - current.web_origins,
    )

    def gone(entries: frozenset[str], kept: frozenset[str]) -> frozenset[str]:
        out = set()
        for entry in entries - kept:
            host = managed_host(client, entry)
            if host is not None and (removable is None or host in removable):
                out.add(entry)
        return frozenset(out)

    remove = Addresses(
        redirect_uris=gone(current.redirect_uris, want.redirect_uris),
        web_origins=gone(current.web_origins, want.web_origins),
    )
    return Change(client.client_id, add, remove)
