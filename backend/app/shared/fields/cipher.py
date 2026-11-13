"""Seal and open field values with the tenant's data keys (ADR-050; D-161; WP-057 S3a).

A value is sealed with the tenant's newest data key (`tenant_data_keys`, files' own, ADR-028)
through the ADR-048 codec: the key ID in the blob is the data key's ID (32 hex characters), the
AES key is HKDF(data key, the purpose), and the blob is bound to (tenant, table, record, field),
so it opens nowhere else. Text form `sx2:...`, for text and JSONB columns.

`open` splits its failures by cause (lane B):
- **the data** is wrong (malformed, a bad tag, a data key this tenant does not have): None,
  logged as `field_unreadable` (purpose, data key ID, reason; never the value or the blob) and
  counted, a bad tag alerted. Callers show "unreadable", never empty, never an error page;
- **the installation key** cannot unwrap the data key (a missing or wrong Secret: operations):
  FieldKeysUnavailable, a 503, so good data is never marked unreadable by a configuration fault.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from opentelemetry import metrics
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ServiceUnavailable
from app.core.logging import get_logger
from app.shared.crypto import KeyMaterial, from_text, key_id_of, open_sealed, seal, to_text
from app.shared.fields.purposes import is_declared
from app.shared.files.keyring import KeyRing, KeyRingError
from app.shared.files.service.core import (
    FilesNotConfiguredError,
    current_data_key,
    data_key,
    tenant_of,
)

log = get_logger(__name__)
_meter = metrics.get_meter("supportx.fields")
_unreadable = _meter.create_counter(
    "supportx_field_unreadable",
    description="Sealed field values that did not open, by purpose and reason (never the value)",
)


class FieldKeysUnavailable(ServiceUnavailable):
    """The installation key cannot unwrap a data key: a configuration fault, not the data's."""

    code = "field_keys_unavailable"


@dataclass(frozen=True)
class Binding:
    """Where a sealed value lives: it opens only there (the tenant comes from the session)."""

    table: str
    record_id: uuid.UUID
    field: str

    def parts(self, tenant_id: uuid.UUID) -> tuple[str, str, str, str]:
        """The codec's `bound_to`: tenant, table, record, field (none may be empty)."""
        if not self.table or not self.field:
            msg = "a sealed value is bound to a table and a field"
            raise ValueError(msg)
        return (str(tenant_id), self.table, str(self.record_id), self.field)


def _checked(purpose: str) -> str:
    if not is_declared(purpose):
        msg = f"field purpose {purpose!r} was never declared (app.shared.fields.purpose)"
        raise ValueError(msg)
    return purpose


@dataclass(frozen=True)
class FieldCipher:
    """Seals and opens one tenant's field values (the session's tenant)."""

    session: AsyncSession
    # The installation's provider (app.shared.crypto.KeyProvider): files' KeyRing today; None
    # when SUPPORTX_FILES_KEYS is not set, and then nothing seals or opens (503).
    keys: KeyRing | None

    def _ring(self) -> KeyRing:
        if self.keys is None:
            raise FieldKeysUnavailable
        return self.keys

    async def seal(self, purpose: str, binding: Binding, value: str) -> str:
        """The value sealed under the tenant's newest data key, as text."""
        tenant = tenant_of(self.session)
        bound = binding.parts(tenant)
        try:
            key_id, secret = await current_data_key(self.session, self._ring())
        except (KeyRingError, FilesNotConfiguredError) as exc:
            raise FieldKeysUnavailable from exc
        key = KeyMaterial(key_id.hex, secret)
        return to_text(seal(key, _checked(purpose), bound, value.encode("utf-8")))

    async def open(self, purpose: str, binding: Binding, text: str) -> str | None:
        """The value, or None when the stored text does not open here (a security event)."""
        tenant = tenant_of(self.session)
        bound = binding.parts(tenant)
        checked = _checked(purpose)
        blob = from_text(text)
        key_ref = key_id_of(blob) if blob is not None else None
        if blob is None or key_ref is None:
            self._unreadable(checked, None, "malformed")
            return None
        try:
            key_uuid = uuid.UUID(hex=key_ref)
        except ValueError:
            self._unreadable(checked, key_ref, "malformed")
            return None
        try:
            secret = await data_key(self.session, self._ring(), key_uuid)
        except FilesNotConfiguredError:
            self._unreadable(checked, key_ref, "unknown_key")
            return None  # not this tenant's
        except KeyRingError as exc:
            raise FieldKeysUnavailable from exc
        found = open_sealed(
            lambda wanted: secret if wanted == key_ref else None, checked, bound, blob
        )
        if found is None:
            self._unreadable(checked, key_ref, "bad_tag")
            return None
        return found.decode("utf-8")

    def _unreadable(self, purpose: str, key_ref: str | None, reason: str) -> None:
        # A security event: someone changed stored data, or it was copied where it does not
        # belong. Never the value, the blob or the record's content (ADR-050 item 4).
        log.warning("field_unreadable", purpose=purpose, data_key=key_ref, reason=reason)
        _unreadable.add(1, {"purpose": purpose, "reason": reason})
        if reason == "bad_tag":
            log.error("field_tampered", purpose=purpose, data_key=key_ref)


def field_cipher(session: AsyncSession, keys: KeyRing | None) -> FieldCipher:
    """The cipher for the session's tenant, with the installation's key provider."""
    return FieldCipher(session, keys)


__all__: Sequence[str] = ("Binding", "FieldCipher", "FieldKeysUnavailable", "field_cipher")
