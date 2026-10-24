"""Anchor signing keys: Ed25519 via `cryptography` (D-021, D-075; ADR-027).

The installation key signs anchors. Its public half, and the public halves of retired keys, are
the trusted keys a verifier accepts; a key found only in the database is never trusted (someone
able to rewrite the database could insert their own). A KMS or HSM signer can implement
`AnchorSigner` later without changing the anchor format.
"""

import base64
import binascii
from dataclasses import dataclass
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

KEY_ID_MAX = 40


class KeyConfigError(ValueError):
    """A configured key is malformed (the message never contains key material)."""


class AnchorSigner(Protocol):
    """Signs anchors. The local Ed25519 key today; a KMS or HSM later."""

    @property
    def key_id(self) -> str:
        """Names the key in anchors and in the trusted-key list."""
        ...

    @property
    def public_key(self) -> bytes:
        """The 32-byte Ed25519 public key."""
        ...

    def sign(self, message: bytes) -> bytes:
        """64-byte Ed25519 signature of `message`."""
        ...


def _split(entry: str) -> tuple[str, bytes]:
    key_id, sep, encoded = entry.strip().partition(":")
    if not sep or not key_id or len(key_id) > KEY_ID_MAX:
        msg = "audit key must look like '<key id>:<base64>'"
        raise KeyConfigError(msg)
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        msg = f"audit key {key_id!r} is not valid base64"
        raise KeyConfigError(msg) from exc
    if len(raw) != 32:  # noqa: PLR2004 - Ed25519 keys are 32 bytes
        msg = f"audit key {key_id!r} must be 32 bytes"
        raise KeyConfigError(msg)
    return key_id, raw


@dataclass(frozen=True)
class LocalSigner:
    """The installation key held in memory (from a Kubernetes secret)."""

    key_id: str
    public_key: bytes
    _private: Ed25519PrivateKey

    @classmethod
    def from_config(cls, value: str) -> "LocalSigner":
        """`<key id>:<base64 seed>` → signer."""
        key_id, seed = _split(value)
        private = Ed25519PrivateKey.from_private_bytes(seed)
        public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return cls(key_id, public, private)

    def sign(self, message: bytes) -> bytes:
        """Ed25519 signature."""
        return self._private.sign(message)


def trusted_keys(retired: str, active: AnchorSigner | None) -> dict[str, bytes]:
    """Key id → public key, for the active key and every retired one."""
    keys: dict[str, bytes] = {}
    for entry in filter(None, (part.strip() for part in retired.split(","))):
        key_id, public = _split(entry)
        keys[key_id] = public
    if active is not None:
        keys[active.key_id] = active.public_key
    return keys


def signature_valid(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Whether `signature` is `public_key`'s Ed25519 signature of `message`."""
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
    except (InvalidSignature, ValueError):
        return False
    return True


def new_key_config(key_id: str) -> str:
    """A fresh `<key id>:<base64 seed>` value (for installers and `make audit-keygen`)."""
    seed = Ed25519PrivateKey.generate().private_bytes_raw()
    return f"{key_id}:{base64.b64encode(seed).decode()}"
