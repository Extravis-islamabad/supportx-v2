"""API keys (REQ-INT-019, 021; D-128): the key format, its hash, scopes and the rules. Pure.

A key reads `sxk_<tenant>_<key id>_<secret>`: the tenant and key IDs are UUIDs in lowercase
Crockford base32 (26 characters each) and the secret is 32 random bytes in base64url (43
characters). The tenant comes first so the API sets the tenant and finds the key under RLS: there
is never a lookup across tenants. Only an HMAC-SHA-256 of the secret, under a server key kept
outside the database, is stored, so a leaked database alone cannot be used to test guesses.

The pattern is public on purpose (docs/api/keys.md, .gitleaks.toml): secret scanners find leaked
keys by it.
"""

import base64
import hashlib
import hmac
import ipaddress
import re
import secrets
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

PREFIX = "sxk"
# Crockford base32 without padding, lowercase: 26 characters for 128 bits.
_B32 = "0123456789abcdefghjkmnpqrstvwxyz"
_SECRET_BYTES = 32
PATTERN = re.compile(r"^sxk_([0-9a-hjkmnp-tv-z]{26})_([0-9a-hjkmnp-tv-z]{26})_([A-Za-z0-9_-]{43})$")
# The same, unanchored, as published for secret scanners (docs/api/keys.md, .gitleaks.toml).
SCANNER_REGEX = r"sxk_[0-9a-hjkmnp-tv-z]{26}_[0-9a-hjkmnp-tv-z]{26}_[A-Za-z0-9_-]{43}"

DEFAULT_LIFETIME = timedelta(days=90)
MAX_LIFETIME = timedelta(days=366)
NAME_MAX = 100
ALLOWLIST_MAX = 20
LAST_USED_EVERY = timedelta(minutes=1)  # writes of last_used_at, at most this often per key

READ_ACTIONS = frozenset({"view", "read", "export", "search", "list"})


def _encode(value: uuid.UUID) -> str:
    number = value.int
    out = []
    for _ in range(26):
        out.append(_B32[number & 31])
        number >>= 5
    return "".join(reversed(out))


def _decode(text: str) -> uuid.UUID | None:
    number = 0
    for char in text:
        index = _B32.find(char)
        if index < 0:
            return None
        number = number * 32 + index
    if number >= 1 << 128:
        return None
    return uuid.UUID(int=number)


@dataclass(frozen=True)
class NewKey:
    """A key as made: the whole text (shown once) and what is stored."""

    text: str
    last_four: str


def make_key(tenant_id: uuid.UUID, key_id: uuid.UUID) -> NewKey:
    """A fresh key for this tenant and key ID."""
    secret = base64.urlsafe_b64encode(secrets.token_bytes(_SECRET_BYTES)).rstrip(b"=").decode()
    text = f"{PREFIX}_{_encode(tenant_id)}_{_encode(key_id)}_{secret}"
    return NewKey(text=text, last_four=text[-4:])


@dataclass(frozen=True)
class ParsedKey:
    """The parts of a presented key."""

    tenant_id: uuid.UUID
    key_id: uuid.UUID
    secret: str


def parse_key(text: str) -> ParsedKey | None:
    """The key's parts, or None when it is not a SupportX key at all."""
    match = PATTERN.match(text.strip())
    if match is None:
        return None
    tenant_id, key_id = _decode(match.group(1)), _decode(match.group(2))
    if tenant_id is None or key_id is None:
        return None
    return ParsedKey(tenant_id=tenant_id, key_id=key_id, secret=match.group(3))


def secret_hash(server_key: bytes, key_id: uuid.UUID, secret: str) -> bytes:
    """HMAC-SHA-256 of the secret, bound to its key ID (a hash never fits another key)."""
    return hmac.new(server_key, key_id.bytes + secret.encode(), hashlib.sha256).digest()


def secret_matches(server_key: bytes, key_id: uuid.UUID, secret: str, stored: bytes) -> bool:
    """Constant-time comparison with the stored hash."""
    return hmac.compare_digest(secret_hash(server_key, key_id, secret), stored)


# --- scopes ----------------------------------------------------------------------------------


def scope_of(permission: str) -> str:
    """`incidents.view` → `incidents:read`; `incidents.create` → `incidents:write`."""
    area, _, action = permission.partition(".")
    kind = "read" if action.split("_", 1)[0] in READ_ACTIONS else "write"
    return f"{area}:{kind}"


def scopes_for(permissions: Iterable[str]) -> list[str]:
    """Every scope the catalogue's permissions make, sorted (read and write per area)."""
    areas = sorted({p.partition(".")[0] for p in permissions})
    return [f"{area}:{kind}" for area in areas for kind in ("read", "write")]


def covered(permission: str, scopes: frozenset[str]) -> bool:
    """Whether a key with these scopes may use `permission` (the owner must still hold it)."""
    return scope_of(permission) in scopes


# --- the rules -------------------------------------------------------------------------------


def expiry_problem(
    expires_at: datetime | None, now: datetime, *, allow_non_expiring: bool
) -> str | None:
    """Why this expiry is refused (a problem code), or None."""
    if expires_at is None:
        return None if allow_non_expiring else "api_key_expiry_required"
    if expires_at <= now:
        return "api_key_expiry_past"
    if expires_at - now > MAX_LIFETIME:
        return "api_key_expiry_too_far"
    return None


def parse_allowlist(entries: Sequence[str]) -> list[str] | None:
    """Normalised networks ("10.0.0.0/8", "203.0.113.7/32"), or None if one is not valid."""
    networks: list[str] = []
    for entry in entries:
        try:
            networks.append(str(ipaddress.ip_network(entry.strip(), strict=False)))
        except ValueError:
            return None
    return networks


def address_allowed(address: str | None, allowlist: Sequence[str]) -> bool:
    """No allowlist: any address. Otherwise the caller's address must be in one of them."""
    if not allowlist:
        return True
    if address is None:
        return False
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in ipaddress.ip_network(network) for network in allowlist)
