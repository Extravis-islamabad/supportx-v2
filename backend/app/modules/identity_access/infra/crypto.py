"""Encryption of session records at rest (AES-256-GCM, D-021)."""

import hashlib
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_CONTEXT = b"supportx/bff-session/v1"
_NONCE_BYTES = 12


class SessionCipher:
    """Encrypt JSON payloads with AES-256-GCM.

    The store key is bound as associated data, so an encrypted record copied under another key
    (e.g. another session's) fails to decrypt.
    """

    def __init__(self, secret: str) -> None:
        # Any length of configured secret -> a 256-bit key, domain-separated from other uses.
        self._aead = AESGCM(hashlib.sha256(_KEY_CONTEXT + secret.encode()).digest())

    def encrypt(self, payload: dict[str, Any], *, bound_to: str) -> bytes:
        """Nonce || ciphertext+tag."""
        nonce = os.urandom(_NONCE_BYTES)
        plaintext = json.dumps(payload, separators=(",", ":")).encode()
        return nonce + self._aead.encrypt(nonce, plaintext, bound_to.encode())

    def decrypt(self, blob: bytes, *, bound_to: str) -> dict[str, Any] | None:
        """The payload, or None if the blob is corrupt, tampered with or from another key."""
        if len(blob) <= _NONCE_BYTES:
            return None
        try:
            plaintext = self._aead.decrypt(
                blob[:_NONCE_BYTES], blob[_NONCE_BYTES:], bound_to.encode()
            )
        except InvalidTag:
            return None
        data = json.loads(plaintext)
        return data if isinstance(data, dict) else None
