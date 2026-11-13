"""Encryption of session records at rest (AES-256-GCM, D-021) under a key ring (D-162, ADR-048).

New records are sealed as v2 blobs (app/shared/crypto) under the ring's newest key, purpose
`bff-session`, bound to the store key. Every listed key still opens, so adding a key signs no one
out: each record moves to the new key at its next save (sign-in, refresh, touch, tenant switch).

Records written before D-162 are v1 blobs (nonce | ciphertext+tag, no header) under
sha256("supportx/bff-session/v1" + SUPPORTX_SESSION_SECRET). They are opened, read-only, while
the ring lists the key "legacy" (which is SUPPORTX_SESSION_SECRET), and never written again.
"""

import hashlib
import json
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import LEGACY_SESSION_KEY_ID, SESSION_KEY_MIN_BYTES, Settings
from app.shared.crypto import KeyMaterial, KeyRing

PURPOSE = "bff-session"
_V1_CONTEXT = b"supportx/bff-session/v1"
_NONCE_BYTES = 12


def session_ring(settings: Settings) -> KeyRing | None:
    """The session key ring from SUPPORTX_SESSION_KEYS / SUPPORTX_SESSION_SECRET, or None.

    Every key but "legacy" (the secret from before D-162, kept as it was) has at least 32
    bytes of secret; the settings refuse shorter ones already, this holds for any other caller.
    """
    entries = settings.session_key_entries()
    if not entries:
        return None
    keys = [KeyMaterial(key_id, secret.encode()) for key_id, secret in entries]
    for key in keys:
        if key.id != LEGACY_SESSION_KEY_ID and len(key.secret) < SESSION_KEY_MIN_BYTES:
            msg = f"session key {key.id!r} needs at least {SESSION_KEY_MIN_BYTES} bytes of secret"
            raise ValueError(msg)
    return KeyRing.of(keys)


class SessionCipher:
    """Seal and open JSON payloads; the store key is bound as associated data.

    A record copied under another store key (another session's) fails to open.
    """

    def __init__(self, keys: KeyRing | str) -> None:
        # A plain string is a one-key ring "legacy" (SUPPORTX_SESSION_SECRET alone; tests).
        self.ring = (
            keys
            if isinstance(keys, KeyRing)
            else KeyRing.of([KeyMaterial(LEGACY_SESSION_KEY_ID, keys.encode())])
        )
        legacy = self.ring.lookup(LEGACY_SESSION_KEY_ID)
        # The pre-D-162 derivation, byte for byte, only to read records sealed before.
        self._v1 = AESGCM(hashlib.sha256(_V1_CONTEXT + legacy).digest()) if legacy else None

    @classmethod
    def from_settings(cls, settings: Settings) -> "SessionCipher | None":
        """The cipher of the configured ring, or None where no session key is set."""
        ring = session_ring(settings)
        return cls(ring) if ring is not None else None

    def encrypt(self, payload: dict[str, Any], *, bound_to: str) -> bytes:
        """A v2 blob under the newest key."""
        plaintext = json.dumps(payload, separators=(",", ":")).encode()
        return self.ring.seal(PURPOSE, (bound_to,), plaintext)

    def decrypt(self, blob: bytes, *, bound_to: str) -> dict[str, Any] | None:
        """The payload, or None if the blob is corrupt, tampered with or from no listed key."""
        plaintext = self.ring.open(PURPOSE, (bound_to,), blob)
        if plaintext is None:
            # A v1 blob, whose random first byte may even look like the v2 header (1 in 256).
            plaintext = self._open_v1(blob, bound_to)
        if plaintext is None:
            return None
        data = json.loads(plaintext)
        return data if isinstance(data, dict) else None

    def is_current(self, blob: bytes) -> bool:
        """Whether a blob is already sealed under the newest key."""
        return self.ring.is_current(blob)

    def _open_v1(self, blob: bytes, bound_to: str) -> bytes | None:
        if self._v1 is None or len(blob) <= _NONCE_BYTES:
            return None
        try:
            return self._v1.decrypt(blob[:_NONCE_BYTES], blob[_NONCE_BYTES:], bound_to.encode())
        except InvalidTag:
            return None
