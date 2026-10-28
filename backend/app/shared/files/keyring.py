"""The installation key ring that wraps each tenant's data keys (D-082 D2, ADR-028 item 2).

`SUPPORTX_FILES_KEYS` = "<key id>:<base64 32 bytes>, <older id>:<base64>, ..." with the active key
first. A tenant data key is stored only wrapped by one of these (AES-256-GCM, bound to the tenant),
so the database alone never reveals a file. Rotation: put a new key first and keep the old ones
listed; `rewrap` moves stored data keys to the new key, after which old keys can be dropped.
Losing every key loses every file: the ring is backed up with the installation's other secrets
(docs/architecture/files.md, "Backup and restore").
"""

import base64
import binascii
import hashlib
import hmac
import os
import re
import uuid
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32
_NONCE = 12
_WRAP_CONTEXT = b"sx-files-dek-v1"
_LINK_CONTEXT = b"sx-files-link-v1"
_SECRET_CONTEXT = b"sx-secret-v1:"
_ID = re.compile(r"^[A-Za-z0-9._-]{1,32}$")


class KeyRingError(ValueError):
    """The key ring setting is malformed, or a wrapped key belongs to no listed key."""


@dataclass(frozen=True)
class KeyRing:
    """Installation keys by ID; the first is used for new wrapping."""

    keys: dict[str, bytes] = field(repr=False)
    active_id: str

    @classmethod
    def parse(cls, value: str) -> "KeyRing":
        """Read the `SUPPORTX_FILES_KEYS` format."""
        keys: dict[str, bytes] = {}
        order: list[str] = []
        for part in (p.strip() for p in value.split(",")):
            if not part:
                continue
            key_id, _, encoded = part.partition(":")
            try:
                key = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as error:
                msg = f"files key {key_id!r} is not base64"
                raise KeyRingError(msg) from error
            if not _ID.match(key_id) or len(key) != KEY_BYTES or key_id in keys:
                msg = f"files key {key_id!r} must be a unique id and 32 random bytes"
                raise KeyRingError(msg)
            keys[key_id] = key
            order.append(key_id)
        if not order:
            msg = "no files key configured"
            raise KeyRingError(msg)
        return cls(keys=keys, active_id=order[0])

    @staticmethod
    def generate(key_id: str = "k1") -> str:
        """A new setting value with one random key (installers, tests)."""
        return f"{key_id}:{base64.b64encode(os.urandom(KEY_BYTES)).decode()}"

    def wrap(self, tenant_id: uuid.UUID, data_key: bytes) -> tuple[str, bytes]:
        """(key id, wrapped bytes) for a tenant data key, under the active key."""
        nonce = os.urandom(_NONCE)
        sealed = AESGCM(self.keys[self.active_id]).encrypt(
            nonce, data_key, _WRAP_CONTEXT + tenant_id.bytes
        )
        return self.active_id, nonce + sealed

    def unwrap(self, tenant_id: uuid.UUID, key_id: str, wrapped: bytes) -> bytes:
        """The tenant data key; KeyRingError when the key is unknown or the bytes were changed."""
        key = self.keys.get(key_id)
        if key is None:
            msg = f"files key {key_id!r} is not in the key ring (restored without it?)"
            raise KeyRingError(msg)
        try:
            return AESGCM(key).decrypt(
                wrapped[:_NONCE], wrapped[_NONCE:], _WRAP_CONTEXT + tenant_id.bytes
            )
        except Exception as error:  # InvalidTag: another tenant's key, or tampered
            msg = "a wrapped data key does not open with its installation key"
            raise KeyRingError(msg) from error

    def seal(self, tenant_id: uuid.UUID, purpose: str, value: bytes) -> tuple[str, bytes]:
        """(key id, sealed bytes) of a tenant secret (a mailbox password…), bound to its purpose.

        Same keys as file data keys, another context: a sealed secret never opens as a data
        key, nor as a secret of another purpose or tenant.
        """
        nonce = os.urandom(_NONCE)
        context = _SECRET_CONTEXT + purpose.encode() + b"\0" + tenant_id.bytes
        sealed = AESGCM(self.keys[self.active_id]).encrypt(nonce, value, context)
        return self.active_id, nonce + sealed

    def unseal(self, tenant_id: uuid.UUID, purpose: str, key_id: str, sealed: bytes) -> bytes:
        """The secret; KeyRingError when the key is unknown or the bytes were changed."""
        key = self.keys.get(key_id)
        if key is None:
            msg = f"files key {key_id!r} is not in the key ring (restored without it?)"
            raise KeyRingError(msg)
        context = _SECRET_CONTEXT + purpose.encode() + b"\0" + tenant_id.bytes
        try:
            return AESGCM(key).decrypt(sealed[:_NONCE], sealed[_NONCE:], context)
        except Exception as error:  # InvalidTag: another tenant's or purpose's secret, or tampered
            msg = "a sealed secret does not open with its installation key"
            raise KeyRingError(msg) from error

    def needs_rewrap(self, key_id: str) -> bool:
        """Whether a data key is wrapped by an older installation key."""
        return key_id != self.active_id

    def link_key(self) -> bytes:
        """The HMAC key for download links (derived; links live minutes, rotation is harmless)."""
        return hmac.new(self.keys[self.active_id], _LINK_CONTEXT, hashlib.sha256).digest()
