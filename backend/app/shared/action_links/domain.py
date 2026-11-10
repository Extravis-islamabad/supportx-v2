"""Signed one-time action links: the pure rules (WP-030 s3; REQ-NTF-024, REQ-SR-026).

Lane B's security conditions (agreed 2026-11-04) shape every rule here:

1. GET never acts: a link opens a page; only an explicit POST of the token does anything.
2. The token is 32 random bytes (URL-safe base64, 43 characters), stored only as its SHA-256
   in a tenant table with RLS; bound to one recipient, one action, one object and the object's
   version; single use; a short expiry. No signing key is needed: the token is a random
   secret looked up by its hash, never a signed claim.
3. The token never reaches logs or a Referer: it travels in the URL fragment (`#…`), which
   browsers never send, and the page posts it in a request body.
4. Every use is audited as the recipient, refusals included (the service), and the routes are
   rate-limited (the API).
5. A policy check at use time: the action's own handler decides again with what is true now.
"""

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

TOKEN_BYTES = 32
TOKEN_LENGTH = 43  # base64url of 32 bytes, unpadded
DEFAULT_TTL = timedelta(hours=72)  # D-132: e-mail approval links
MAX_TTL = timedelta(days=7)
MAX_FAILED_USES = 5  # refused uses of one link before it is revoked (lane B review)


class Refusal(StrEnum):
    """Why a link does nothing (shown as a plain page; audited)."""

    # Unknown, malformed, another tenant's, someone else's, or already used: one answer, so a
    # forwarded or replayed link tells its holder nothing (lane B review).
    NOT_FOUND = "action_link_not_found"
    EXPIRED = "action_link_expired"
    # No longer needed: decided another way, withdrawn, its approver changed (REQ-SR-061 AC2).
    REVOKED = "action_link_revoked"
    SIGN_IN_REQUIRED = "action_link_sign_in_required"  # the tenant asks for a signed-in approver


@dataclass(frozen=True)
class NewToken:
    """A fresh token: the secret for the link, and the hash that is stored."""

    secret: str
    digest: bytes


def new_token() -> NewToken:
    """32 random bytes from the OS's CSPRNG; only the digest is ever stored."""
    secret = base64.urlsafe_b64encode(secrets.token_bytes(TOKEN_BYTES)).rstrip(b"=").decode()
    return NewToken(secret=secret, digest=digest_of(secret))


def digest_of(secret: str) -> bytes:
    """SHA-256 of the token text (a random 256-bit secret needs no slow hash)."""
    return hashlib.sha256(secret.encode("ascii", errors="replace")).digest()


def well_formed(secret: str) -> bool:
    """Shape check before any lookup: 43 base64url characters."""
    if len(secret) != TOKEN_LENGTH:
        return False
    alphabet = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    return set(secret) <= alphabet


@dataclass(frozen=True)
class LinkState:
    """What the rules look at of a stored link."""

    recipient_id: uuid.UUID
    object_version: int
    expires_at: datetime
    used_at: datetime | None
    revoked_at: datetime | None


def refusal(
    link: LinkState | None,
    *,
    now: datetime,
    actor: uuid.UUID | None,
    current_version: int | None,
) -> Refusal | None:
    """Why the link may not act now, or None.

    Order: unknown, not theirs or used (one answer, lane B), revoked, expired, stale. `actor`
    None: the no-sign-in mode (D-132), where the token itself stands for its recipient.
    `current_version` None: the object is gone or no longer waits, so the link is spent.
    """
    if link is None or link.used_at is not None:
        return Refusal.NOT_FOUND
    if actor is not None and not hmac.compare_digest(actor.bytes, link.recipient_id.bytes):
        return Refusal.NOT_FOUND
    if link.revoked_at is not None:
        return Refusal.REVOKED
    if now >= link.expires_at:
        return Refusal.EXPIRED
    if current_version is None or current_version != link.object_version:
        return Refusal.REVOKED
    return None


@dataclass(frozen=True)
class LinkRequest:
    """A link to make for one recipient when their message is sent, never before (D-132).

    What is stored with a queued message instead of the token: rendered bodies carry a marker
    where the link goes, and the mail sender mints the token at send time, so no stored body,
    delivery row or log ever holds one (Haider's addition to D-132).
    """

    recipient_id: uuid.UUID
    action: str
    object_type: str
    object_id: uuid.UUID
    object_version: int


def public_page(tenant_slug: str) -> str:
    """The portal's public confirmation page (D-132), up to the token, which follows the `#`.

    `?t=` names the tenant by slug, for addresses that name none (on-prem and k3s without tenant
    subdomains); never its id. The token stays in the fragment: never sent to a server, never
    in an access log.
    """
    return f"approve?t={tenant_slug}#" if tenant_slug else "approve#"


def marker(name: str) -> str:
    """Where a link goes in a stored body (plain ASCII, unchanged by HTML escaping)."""
    return f"[[supportx-link:{name}]]"


def expiry(now: datetime, ttl: timedelta = DEFAULT_TTL) -> datetime:
    """When a link issued now stops working (never longer than MAX_TTL)."""
    return now + min(ttl, MAX_TTL)


__all__ = [
    "DEFAULT_TTL",
    "MAX_FAILED_USES",
    "MAX_TTL",
    "TOKEN_LENGTH",
    "LinkRequest",
    "LinkState",
    "NewToken",
    "Refusal",
    "digest_of",
    "expiry",
    "marker",
    "new_token",
    "public_page",
    "refusal",
    "well_formed",
]
