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
DEFAULT_TTL = timedelta(hours=72)  # plan D7: e-mail approval links
MAX_TTL = timedelta(days=7)


class Refusal(StrEnum):
    """Why a link does nothing (shown as a plain page; audited)."""

    NOT_FOUND = "action_link_not_found"  # unknown, malformed or another tenant's
    EXPIRED = "action_link_expired"
    USED = "action_link_used"
    REVOKED = "action_link_revoked"  # e.g. the request was withdrawn (REQ-SR-061 AC2)
    WRONG_RECIPIENT = "action_link_wrong_recipient"
    STALE = "action_link_stale"  # the object changed since the link was sent


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


def refusal(  # noqa: PLR0911 - one return per refusal, in their fixed order
    link: LinkState | None,
    *,
    now: datetime,
    actor: uuid.UUID | None,
    current_version: int | None,
) -> Refusal | None:
    """Why the link may not act now, or None. Order: unknown, used, revoked, expired, who, stale.

    `actor` None: nobody is signed in (the no-sign-in mode, behind a tenant setting that is
    off, plan D7); the token itself then stands for the recipient.
    """
    if link is None:
        return Refusal.NOT_FOUND
    if link.used_at is not None:
        return Refusal.USED
    if link.revoked_at is not None:
        return Refusal.REVOKED
    if now >= link.expires_at:
        return Refusal.EXPIRED
    if actor is not None and not hmac.compare_digest(actor.bytes, link.recipient_id.bytes):
        return Refusal.WRONG_RECIPIENT
    if current_version is not None and current_version != link.object_version:
        return Refusal.STALE
    return None


def expiry(now: datetime, ttl: timedelta = DEFAULT_TTL) -> datetime:
    """When a link issued now stops working (never longer than MAX_TTL)."""
    return now + min(ttl, MAX_TTL)


__all__ = [
    "DEFAULT_TTL",
    "MAX_TTL",
    "TOKEN_LENGTH",
    "LinkState",
    "NewToken",
    "Refusal",
    "digest_of",
    "expiry",
    "new_token",
    "refusal",
    "well_formed",
]
