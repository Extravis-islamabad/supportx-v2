"""Field encryption (ADR-050; D-161; WP-057 S3a): what modules call to seal and open values.

Modules import only from here: `purpose` to declare theirs, `field_cipher` and `Binding` to seal
and open, `FieldKeysUnavailable` for the 503. The key provider and the data keys stay inside.
"""

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

_process_cache: DataKeyCache | None = None
_rings: dict[str, KeyRing] = {}


def process_cache(settings: Settings) -> DataKeyCache | None:
    """The data-key cache of this process (one per process), or None without Valkey (no cache)."""
    global _process_cache  # noqa: PLW0603 - one cache per process, by design (ADR-050)
    if settings.valkey_url is None:
        return None
    if _process_cache is None:
        _process_cache = DataKeyCache(ValkeyGenerations(valkey_client(settings)))
    return _process_cache


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
