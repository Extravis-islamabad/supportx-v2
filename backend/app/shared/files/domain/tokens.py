"""Short-lived download links (REQ-INC-079 AC3): who may fetch which file, how, until when.

A link token is `<payload>.<signature>` in URL-safe base64: the file, the user it was issued to,
their tenant, the disposition (preview in the browser or download) and the expiry, signed with
HMAC-SHA256. The content route checks the signature and the expiry, then checks the user's access
again: a token never grants more than its user may see at the moment of the download.
"""

import base64
import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

_VERSION = 1
_PAYLOAD = 1 + 16 * 3 + 8 + 1


class Disposition(StrEnum):
    """Open in the browser (images, PDFs) or save as a file."""

    INLINE = "inline"
    ATTACHMENT = "attachment"


_CODES = {Disposition.INLINE: 1, Disposition.ATTACHMENT: 2}
_FROM_CODE = {code: value for value, code in _CODES.items()}


class TokenError(ValueError):
    """The token is malformed, forged or expired (`expired` tells the last case apart)."""

    def __init__(self, *, expired: bool = False) -> None:
        super().__init__("expired link" if expired else "invalid link")
        self.expired = expired


@dataclass(frozen=True)
class LinkGrant:
    """What a valid token allows."""

    file_id: uuid.UUID
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    disposition: Disposition
    expires_at: datetime


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(grant: LinkGrant, key: bytes) -> str:
    """The token for `grant`."""
    payload = (
        bytes([_VERSION])
        + grant.file_id.bytes
        + grant.user_id.bytes
        + grant.tenant_id.bytes
        + int(grant.expires_at.timestamp()).to_bytes(8, "big")
        + bytes([_CODES[grant.disposition]])
    )
    signature = hmac.new(key, payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(signature)}"


def verify(token: str, key: bytes, now: datetime) -> LinkGrant:
    """The grant of a valid, unexpired token, else TokenError."""
    try:
        encoded_payload, encoded_signature = token.split(".")
        payload, signature = _unb64(encoded_payload), _unb64(encoded_signature)
    except ValueError as error:
        raise TokenError from error
    expected = hmac.new(key, payload, hashlib.sha256).digest()
    if (
        len(payload) != _PAYLOAD
        or payload[0] != _VERSION
        or not hmac.compare_digest(signature, expected)
    ):
        raise TokenError
    disposition = _FROM_CODE.get(payload[-1])
    if disposition is None:
        raise TokenError
    expires_at = datetime.fromtimestamp(int.from_bytes(payload[49:57], "big"), UTC)
    if now >= expires_at:
        raise TokenError(expired=True)
    return LinkGrant(
        file_id=uuid.UUID(bytes=payload[1:17]),
        user_id=uuid.UUID(bytes=payload[17:33]),
        tenant_id=uuid.UUID(bytes=payload[33:49]),
        disposition=disposition,
        expires_at=expires_at,
    )
