"""Sealed blobs and key rings (ADR-048, D-162): one format for every secret SupportX encrypts.

* `codec`: `KeyMaterial`, `seal`, `open_sealed`, `to_text` / `from_text` (pure, no I/O);
* `ring`: `KeyRing`, keys newest first, the newest seals and any listed key opens;
* `users`: `register_key_user`, the "who still uses key X" hook checked at start-up.

First user: the BFF session cipher (identity_access). WP-057's field encryption reuses the format.
"""

from app.shared.crypto.codec import (
    KeyMaterial,
    check_key_id,
    from_text,
    key_id_of,
    open_sealed,
    seal,
    to_text,
)
from app.shared.crypto.ring import KeyRing
from app.shared.crypto.users import (
    KeyStillInUseError,
    KeyUserCount,
    key_users,
    refuse_if_still_used,
    register_key_user,
    unregister_key_user,
)

__all__ = [
    "KeyMaterial",
    "KeyRing",
    "KeyStillInUseError",
    "KeyUserCount",
    "check_key_id",
    "from_text",
    "key_id_of",
    "key_users",
    "open_sealed",
    "refuse_if_still_used",
    "register_key_user",
    "seal",
    "to_text",
    "unregister_key_user",
]
