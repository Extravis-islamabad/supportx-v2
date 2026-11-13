"""Field encryption (ADR-050; D-161; WP-057 S3a): what modules call to seal and open values.

Modules import only from here: `purpose` to declare theirs, `field_cipher` and `Binding` to seal
and open, `FieldKeysUnavailable` for the 503. The key provider and the data keys stay inside.
"""

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

_process_cache: DataKeyCache | None = None


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
    "process_cache",
    "purpose",
]
