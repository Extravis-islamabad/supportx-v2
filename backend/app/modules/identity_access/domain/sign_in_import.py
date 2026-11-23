"""What the Keycloak events import reads and where an event belongs (WP-057 S1b). Pure: no I/O.

Only what Keycloak decides is imported (a wrong password, a lock-out, an identity provider's
refusal): the BFF writes every sign-in it completes or refuses itself, so successes are never
read twice. Events from the console and portal clients only: a service account's own token
requests are no person's sign-in.

**Which tenant** (lane B's review of S1a, never every tenant a person is in): the identity
provider's alias names its tenant (`sx-<slug>-<token>`, confirmed against that tenant's own
providers), else the address the attempt was sent back to (a tenant's subdomain or verified
domain). An attempt on the shared address names no tenant: it is counted, never guessed.
"""

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.modules.identity_access.domain.sign_in import SignInApp, SignInMethod

IMPORT_TYPES = (
    "LOGIN_ERROR",
    "IDENTITY_PROVIDER_LOGIN_ERROR",
    "IDENTITY_PROVIDER_FIRST_LOGIN_ERROR",
    "IDENTITY_PROVIDER_POST_LOGIN_ERROR",
)
CLIENT_APPS = {"supportx-console": SignInApp.CONSOLE, "supportx-portal": SignInApp.PORTAL}
EVENT_ID_MAX = 64  # sign_in_events.keycloak_event_id
ALIAS_PREFIX = "sx-"


@dataclass(frozen=True)
class KeycloakEvent:
    """One realm event, only the parts the import reads (never the typed user name)."""

    id: str
    type: str
    time_ms: int
    client_id: str | None
    error: str | None
    user_id: str | None
    ip: str | None
    identity_provider: str | None
    redirect_uri: str | None
    credential_type: str | None = None  # a credential event's (REQ-SEC-033 part 2), else None


def app_of(event: KeycloakEvent) -> SignInApp | None:
    """The SupportX app the attempt was made in, or None (not a person's sign-in: skipped)."""
    return CLIENT_APPS.get(event.client_id or "")


def method_of(event: KeycloakEvent) -> SignInMethod:
    """Single sign-on when an identity provider took part, else a password."""
    return SignInMethod.SINGLE_SIGN_ON if event.identity_provider else SignInMethod.PASSWORD


def slug_of_alias(alias: str | None) -> str | None:
    """The tenant slug an alias was made with (`sx-acme-1a2b3c` → `acme`), else None.

    A hint only: the import confirms the alias is that tenant's own provider before using it.
    """
    if not alias or not alias.startswith(ALIAS_PREFIX):
        return None
    slug, _sep, _token = alias[len(ALIAS_PREFIX) :].rpartition("-")
    return slug or None


def redirect_host(uri: str | None) -> str | None:
    """The host the attempt was to come back to, or None."""
    if not uri:
        return None
    try:
        return urlsplit(uri).hostname
    except ValueError:
        return None


def clean_ip(value: str | None) -> str | None:
    """An address the log can keep (INET), else None."""
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def usable(event: KeycloakEvent) -> bool:
    """Whether the event can be stored at all (an ID that fits the column)."""
    return 0 < len(event.id) <= EVENT_ID_MAX
