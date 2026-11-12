"""The sealed-blob codec (ADR-048): AES-256-GCM under a per-purpose HKDF key, with a key ID.

Pure: no I/O, no settings. A caller hands in key material (`seal`) or a way to find it by ID
(`open_sealed`); where keys come from is the ring's business (ring.py), not the codec's.

Blob v2 = 0x02 | len(key_id) | key_id (ASCII) | 12-byte nonce | ciphertext + 16-byte tag.
The associated data binds the purpose, the key ID and the caller's `bound_to` parts, so a blob
never opens for another purpose, under another key ID or for another record.
"""

import base64
import binascii
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VERSION = 0x02
NONCE_BYTES = 12
TAG_BYTES = 16
KEY_BYTES = 32
TEXT_PREFIX = "sx2:"
KEY_ID_PATTERN = re.compile(r"^[a-z0-9_-]{1,32}$")
PURPOSE_PATTERN = re.compile(r"^[a-z0-9_./-]{1,64}$")
_SEPARATOR = b"\x00"
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]*$")

KeyLookup = Callable[[str], bytes | None]


def check_key_id(key_id: str) -> str:
    """The key ID, or ValueError: lowercase letters, digits, `_` and `-`, 1 to 32 characters."""
    if not KEY_ID_PATTERN.fullmatch(key_id):
        msg = "key IDs are 1 to 32 of a-z, 0-9, '_' and '-'"
        raise ValueError(msg)
    return key_id


def _check_purpose(purpose: str) -> bytes:
    if not PURPOSE_PATTERN.fullmatch(purpose):
        msg = "purposes are 1 to 64 of a-z, 0-9, '_', '.', '/' and '-'"
        raise ValueError(msg)
    return purpose.encode("ascii")


def _bound_bytes(bound_to: Sequence[str]) -> bytes:
    """The parts joined by NUL: at least one part, each non-empty and NUL-free (else ValueError).

    So ("a", "bc") and ("ab", "c") can never produce the same bytes.
    """
    if isinstance(bound_to, str):
        msg = "bound_to is a sequence of parts, not one string"
        raise TypeError(msg)
    if not bound_to:
        msg = "bound_to needs at least one part"
        raise ValueError(msg)
    encoded: list[bytes] = []
    for part in bound_to:
        if not part or "\x00" in part:
            msg = "every bound_to part must be non-empty and hold no NUL character"
            raise ValueError(msg)
        encoded.append(part.encode("utf-8"))
    return _SEPARATOR.join(encoded)


@dataclass(frozen=True)
class KeyMaterial:
    """One key: its ID (stored in every blob it seals) and its secret (never in a repr)."""

    id: str
    secret: bytes = field(repr=False)

    def __post_init__(self) -> None:  # noqa: D105 - validation only
        check_key_id(self.id)
        if not self.secret:
            msg = "a key needs a secret"
            raise ValueError(msg)


@lru_cache(maxsize=128)
def _derived(secret: bytes, purpose: bytes) -> AESGCM:
    # One AES key per purpose (HKDF-SHA256, RFC 5869): a key ring shared by several uses never
    # encrypts two of them under the same AES key. Cached: a session is opened on every request.
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=None,
        info=b"supportx/" + purpose + b"/v2",
    ).derive(secret)
    return AESGCM(key)


def _aad(purpose: bytes, key_id: bytes, bound_to: Sequence[str]) -> bytes:
    return (
        b"supportx/" + purpose + b"/v2" + _SEPARATOR + key_id + _SEPARATOR + _bound_bytes(bound_to)
    )


def seal(key: KeyMaterial, purpose: str, bound_to: Sequence[str], plaintext: bytes) -> bytes:
    """A v2 blob of `plaintext` under `key`, for `purpose`, bound to `bound_to`."""
    purpose_bytes = _check_purpose(purpose)
    key_id = check_key_id(key.id).encode("ascii")
    aad = _aad(purpose_bytes, key_id, bound_to)
    nonce = os.urandom(NONCE_BYTES)
    sealed = _derived(key.secret, purpose_bytes).encrypt(nonce, plaintext, aad)
    return bytes([VERSION, len(key_id)]) + key_id + nonce + sealed


def key_id_of(blob: bytes) -> str | None:
    """The key ID a v2 blob names, or None when it is no well-formed v2 blob (no decryption)."""
    if len(blob) < 2 or blob[0] != VERSION:  # noqa: PLR2004 - version byte and length byte
        return None
    size = blob[1]
    end = 2 + size
    if len(blob) < end + NONCE_BYTES + TAG_BYTES:
        return None
    try:
        key_id = blob[2:end].decode("ascii")
    except UnicodeDecodeError:
        return None
    return key_id if KEY_ID_PATTERN.fullmatch(key_id) else None


def open_sealed(
    lookup: KeyLookup, purpose: str, bound_to: Sequence[str], blob: bytes
) -> bytes | None:
    """The plaintext, or None for an unknown key ID, a bad tag or a malformed blob.

    A wrong `purpose` or `bound_to` is a bad tag. A malformed `purpose` or `bound_to` is the
    caller's mistake and raises ValueError, as in `seal`.
    """
    purpose_bytes = _check_purpose(purpose)
    _bound_bytes(bound_to)  # validated before anything about the blob is looked at
    key_id = key_id_of(blob)
    if key_id is None:
        return None
    secret = lookup(key_id)
    if not secret:
        return None
    start = 2 + len(key_id)
    nonce = blob[start : start + NONCE_BYTES]
    aad = _aad(purpose_bytes, key_id.encode("ascii"), bound_to)
    try:
        return _derived(secret, purpose_bytes).decrypt(nonce, blob[start + NONCE_BYTES :], aad)
    except InvalidTag:
        return None


def to_text(blob: bytes) -> str:
    """The text form, for text columns and JSON: "sx2:" + base64url without padding."""
    return TEXT_PREFIX + base64.urlsafe_b64encode(blob).rstrip(b"=").decode("ascii")


def from_text(text: str) -> bytes | None:
    """The blob of a text form, or None when it is not one (wrong prefix, bad base64)."""
    if not text.startswith(TEXT_PREFIX):
        return None
    body = text[len(TEXT_PREFIX) :]
    if not _BASE64URL.fullmatch(body):
        return None
    try:
        return base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except (binascii.Error, ValueError):  # a length no base64 can have
        return None
