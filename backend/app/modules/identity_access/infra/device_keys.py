"""The "known-device" HMAC keys, from the session ring (WP-057 S2b-1; ADR-048; the coordinator).

A dedicated purpose key per ring key: HKDF-SHA256 of the ring secret with the ADR-048 label
scheme (`supportx/known-device/v2`), so a fingerprint key is never the session's AES key nor the
API-key or cursor key, even from the same secret. Newest key first, as the ring lists them: a
sign-in is checked under each, so rotating the ring never makes every device "new".
"""

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.shared.crypto import KeyRing

PURPOSE = b"supportx/known-device/v2"
KEY_BYTES = 32


def _derive(secret: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None, info=PURPOSE).derive(secret)


def device_keys(ring: KeyRing | None) -> tuple[bytes, ...]:
    """The known-device keys, newest first; none without a ring (no fingerprints, no notices)."""
    if ring is None:
        return ()
    keys: list[bytes] = []
    for key_id in ring.ids:
        secret = ring.lookup(key_id)
        if secret is not None:
            keys.append(_derive(secret))
    return tuple(keys)
