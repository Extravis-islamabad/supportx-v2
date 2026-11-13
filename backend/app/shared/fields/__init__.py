"""Field encryption (ADR-050; D-161; WP-057 S3a): what modules call to seal and open values.

Modules import only from here: `purpose` to declare theirs, `field_cipher` and `Binding` to seal
and open, `FieldKeysUnavailable` for the 503. The key provider and the data keys stay inside.
"""

import asyncio
import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.valkey import client as valkey_client
from app.shared.fields.cache import (
    DataKeyCache,
    Generations,
    GenerationsUnavailable,
    ValkeyGenerations,
    destroy_tenant_keys,
)
from app.shared.fields.cipher import Binding, FieldCipher, FieldKeysUnavailable, field_cipher
from app.shared.fields.purposes import PurposeError, purpose
from app.shared.files.keyring import KeyRing, KeyRingError

# One cache per event loop and Valkey (lane B, 2026-11-13): a Valkey client belongs to the loop it
# was made on, and tests run each on a loop of their own, with a key prefix of their own.
# Production has one loop and one Valkey per process, so one cache, as ADR-050 says.
_caches: dict[tuple[int, str, str], tuple[asyncio.AbstractEventLoop, DataKeyCache]] = {}
_rings: dict[str, KeyRing] = {}


def process_cache(settings: Settings) -> DataKeyCache | None:
    """The data-key cache for the running loop and Valkey, or None without Valkey (no cache)."""
    if settings.valkey_url is None:
        return None
    loop = asyncio.get_running_loop()
    for stale in [k for k, (owner, _cache) in _caches.items() if owner.is_closed()]:
        del _caches[stale]  # a finished test's loop: its client and keys go with it
    # The URL holds a password: only its digest is kept as a key (str() of it is masked anyway).
    url = hashlib.sha256(settings.valkey_url.get_secret_value().encode()).hexdigest()
    key = (id(loop), url, settings.valkey_key_prefix)
    found = _caches.get(key)
    if found is None or found[0] is not loop:  # an id reused by a new loop is not that loop
        found = (loop, DataKeyCache(ValkeyGenerations(valkey_client(settings))))
        _caches[key] = found
    return found[1]


__all__ = [
    "Binding",
    "DataKeyCache",
    "FieldCipher",
    "FieldKeysUnavailable",
    "Generations",
    "GenerationsUnavailable",
    "PurposeError",
    "ValkeyGenerations",
    "destroy_tenant_keys",
    "field_cipher",
    "field_cipher_for",
    "field_keys",
    "process_cache",
    "purpose",
]


def field_keys(settings: Settings) -> KeyRing | None:
    """The installation's key provider (ADR-050 item 1), chosen here only; None when not set.

    A malformed `SUPPORTX_FILES_KEYS` raises FieldKeysUnavailable (503), as a missing key does.

    Today the installation ring, `SUPPORTX_FILES_KEYS`, parsed once per process per value.
    A customer-managed KMS would be chosen here too, and no module would change.
    """
    secret = settings.files_keys
    if secret is None:
        return None
    value = secret.get_secret_value()
    # Remembered by a hash of the value (lane B): the secret itself is never a dictionary key.
    digest = hashlib.sha256(value.encode()).hexdigest()
    ring = _rings.get(digest)
    if ring is None:
        try:
            ring = KeyRing.parse(value)
        except KeyRingError as exc:  # a malformed setting: an operations fault, never a 500
            raise FieldKeysUnavailable from exc
        _rings.clear()  # one installation ring per process: a new value replaces the old
        _rings[digest] = ring
    return ring


def field_cipher_for(session: AsyncSession, settings: Settings) -> FieldCipher:
    """What a module calls: the cipher for the session's tenant, ready to use.

    The installation's keys and this process's data-key cache are chosen here (lane A), so a
    module needs only `purpose`, `Binding`, `seal` and `open`.
    """
    return field_cipher(session, field_keys(settings), process_cache(settings))
