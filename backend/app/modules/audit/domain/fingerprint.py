r"""The change-set fingerprint of a save's audit entry (WP-064 S2, D-150, ADR-046). Pure: no I/O.

A save's before and after values stay in record history (`field_changes`); its audit entry holds
only a fingerprint of them, inside the entry hash. Record history thereby becomes tamper-evident:
the verifier recomputes the fingerprint from `field_changes` and compares.

The byte layout is specified in full in docs/adr/ADR-046 (so that a verifier written in another
language, years from now, can recompute it) and pinned by a golden-vector test. Never change it:
a new layout gets a new prefix (`fp2:`) and both stay verifiable.

Values (`canonical_value`)
    The JSON value exactly as `field_changes` stores it (JSONB), written as canonical JSON:
    `null`, `true`, `false`; numbers as their decimal value (an integral number as its digits,
    `1.0` as `1`, `-0` as `0`; any other as plain decimal notation with no exponent and no
    trailing zeros, `1.5e-7` as `0.00000015`); strings as JSON strings in UTF-8 (only `"`, `\\`
    and U+0000-U+001F escaped: `\\b \\f \\n \\r \\t`, others as `\\u00xx` lowercase); arrays in
    order; objects with keys sorted by Unicode code point. No whitespace anywhere. Values that
    are not JSON yet (only direct callers pass them) are written as strings: aware datetimes as
    `YYYY-MM-DDTHH:MM:SS.ffffffZ` in UTC, dates as `YYYY-MM-DD`, UUIDs lowercase with hyphens.

Field digest (`value_digest`)
    Lowercase hex of SHA-256(salt_1 ‖ ... ‖ salt_n ‖ canonical value), the salts being those of
    the field's data subjects in subject-ID order. An ordinary field has no subjects, so its
    digest is SHA-256(canonical value). Personal values are thus committed to with salts that
    erasure destroys (crypto-shredding): an erased value cannot be guessed back from the chain.

Change set and fingerprint (`fingerprint`)
    The canonical JSON (same rules) of
        {"record_id": "<uuid>", "record_type": "<history record type>",
         "saves": [{"change_id": "<uuid>", "fields": [[field, digest(old), digest(new),
                    [subject ids]], ...], "kind": "<kind>", "version": <int>}, ...], "v": 1}
    with the saves in the entry's save order and each save's fields sorted (by field, then the
    rest of the tuple). The fingerprint is `fp1:` + lowercase hex SHA-256 of those bytes.
"""

import hashlib
import json
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

PREFIX = "fp1:"
VERSION = 1


class FingerprintError(ValueError):
    """A value cannot be put in canonical form (NaN, a non-string key, an unknown type)."""


class FingerprintStatus(StrEnum):
    """What the verifier says of one fingerprinted entry (labels: `audit_fingerprint_status.*`)."""

    VERIFIED = "verified"  # record history still matches the entry's fingerprint
    MISMATCH = "mismatch"  # record history was changed, or a salt is gone without an erasure
    ERASED_ON_REQUEST = "erased_on_request"  # a subject's salt is gone and their erasure is logged


def _number(value: float) -> str:
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        msg = "NaN and infinity have no JSON form"
        raise FingerprintError(msg)
    # repr() is the shortest text that reads back as the same float, which is also what JSONB
    # keeps (json.dumps writes repr); as a decimal it is the same number either way.
    exact = Decimal(repr(value))
    if exact == exact.to_integral_value():
        return str(int(exact))
    return format(exact.normalize(), "f")


def _string(value: str) -> str:
    # json.dumps with ensure_ascii=False escapes exactly ", \ and U+0000-U+001F (see above).
    return json.dumps(value, ensure_ascii=False)


def _encode(value: object) -> str:  # noqa: C901, PLR0911 - one branch per JSON type
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            msg = "naive datetime in a fingerprinted value"
            raise FingerprintError(msg)
        return _string(value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    if isinstance(value, date):
        return _string(value.isoformat())
    if isinstance(value, uuid.UUID):
        return _string(str(value))
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            msg = "object keys must be strings"
            raise FingerprintError(msg)
        items = sorted(value.items())  # str order is Unicode code point order
        return "{" + ",".join(f"{_string(k)}:{_encode(v)}" for k, v in items) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    msg = f"cannot fingerprint a {type(value).__name__}"
    raise FingerprintError(msg)


def canonical_value(value: object) -> bytes:
    """The canonical JSON bytes of one value (see the module docstring)."""
    return _encode(value).encode("utf-8")


def value_digest(value: object, salts: Sequence[bytes] = ()) -> str:
    """Hex SHA-256 of the subjects' salts (in subject order) followed by the canonical value."""
    return hashlib.sha256(b"".join(salts) + canonical_value(value)).hexdigest()


@dataclass(frozen=True)
class FieldValues:
    """One changed field of a save as history stores it, and whose personal data it is."""

    field: str
    old: object
    new: object
    personal: bool = False


@dataclass(frozen=True)
class SaveValues:
    """One save: its change ID, the record version and kind it was written with, its fields."""

    change_id: uuid.UUID
    version: int
    kind: str
    fields: tuple[FieldValues, ...]


def change_set(
    record_type: str,
    record_id: uuid.UUID,
    saves: Sequence[SaveValues],
    subjects: Sequence[uuid.UUID],
    salts: Mapping[uuid.UUID, bytes],
) -> dict[str, object]:
    """The canonical change set: digests only, never a value.

    `subjects` are the data subjects of the personal fields (the entry stores them); `salts`
    must hold each one's salt. Personal fields are digested with all of them, in ID order.
    """
    ordered = sorted(set(subjects), key=str)
    subject_salts = [salts[s] for s in ordered]  # KeyError: a caller bug, never a guess
    ids = [str(s) for s in ordered]
    out: list[dict[str, object]] = []
    for save in saves:
        fields = sorted(
            (
                f.field,
                value_digest(f.old, subject_salts if f.personal else ()),
                value_digest(f.new, subject_salts if f.personal else ()),
                ids if f.personal else [],
            )
            for f in save.fields
        )
        out.append(
            {
                "change_id": str(save.change_id),
                "fields": [list(f) for f in fields],
                "kind": save.kind,
                "version": save.version,
            }
        )
    return {"record_id": str(record_id), "record_type": record_type, "saves": out, "v": VERSION}


def fingerprint(
    record_type: str,
    record_id: uuid.UUID,
    saves: Sequence[SaveValues],
    subjects: Sequence[uuid.UUID] = (),
    salts: Mapping[uuid.UUID, bytes] | None = None,
) -> str:
    """`fp1:` + hex SHA-256 of the canonical change set."""
    content = change_set(record_type, record_id, saves, subjects, salts or {})
    return PREFIX + hashlib.sha256(canonical_value(content)).hexdigest()


def status_of(  # noqa: PLR0913 - the stored entry's parts and what the database still has
    stored: str,
    recomputed: str | None,
    *,
    subjects: Sequence[uuid.UUID],
    salted: Sequence[uuid.UUID],
    erased_after: Mapping[uuid.UUID, datetime],
    occurred_at: datetime,
) -> FingerprintStatus:
    """The verdict on one entry.

    A subject whose salt is gone makes the entry `erased_on_request` only when that subject's
    erasure was logged after the entry (an `audit.subject_erased` entry, itself in the chain);
    a missing salt without one is a mismatch. With every salt present, the recomputed
    fingerprint must equal the stored one.
    """
    missing = [s for s in subjects if s not in set(salted)]
    if missing:
        logged = all(s in erased_after and erased_after[s] > occurred_at for s in missing)
        return FingerprintStatus.ERASED_ON_REQUEST if logged else FingerprintStatus.MISMATCH
    if recomputed is not None and recomputed == stored:
        return FingerprintStatus.VERIFIED
    return FingerprintStatus.MISMATCH
