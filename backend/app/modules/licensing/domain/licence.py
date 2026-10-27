"""On-prem licence document (architecture.md §13.3): parsing and the signed payload. Pure Python.

The file is JSON:

    {"licence_id": "LIC-2027-00418", "customer": "Example Bank PJSC", "installation_id": "0b9c..",
     "fingerprint": {"algo": "v1", "components": {...}, "min_match": 3},
     "edition": "enterprise", "features": ["problem", "change", ...],
     "limits": {"technicians": 250, "assets": 5000, "desks": 10},
     "issued_at": "2027-01-10", "expires_at": "2028-01-09", "maintenance_until": "2028-01-09",
     "grace_days": 14, "signature": "ed25519:..."}

`features` adds to the edition's features, `limits` overrides the edition defaults (catalogue.py).
Dates are whole UTC days: the licence is valid from the start of `issued_at` through the END of
`expires_at` and `maintenance_until`.

`signed_payload` is the exact byte string the signature covers: every field except `signature`,
as canonical JSON (sorted keys, no whitespace, UTF-8). WP-013's Ed25519 verification and the
dev signing tool both use it, so any edit to any field breaks the signature (§13.3).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from app.modules.licensing.domain.catalogue import Edition, Feature, LimitKey
from app.modules.licensing.domain.entitlement import DEFAULT_GRACE_DAYS, Entitlement, Term

MAX_LICENCE_BYTES = 64 * 1024
MAX_GRACE_DAYS = 90


class LicenceRejectedError(Exception):
    """The licence cannot be used. `reason` is a stable code, logged at startup (§13.6)."""

    def __init__(self, *, reason: str, detail: str = "") -> None:
        self.reason = reason
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass(frozen=True)
class LicenceDocument:
    """A parsed licence. `signature` is None for an unsigned dev licence."""

    licence_id: str
    customer: str
    installation_id: str | None
    fingerprint: Mapping[str, Any] | None
    entitlement: Entitlement
    signature: str | None
    signed_payload: bytes


def signed_payload(data: Mapping[str, Any]) -> bytes:
    """Canonical bytes covered by the signature: all fields but `signature`."""
    body = {key: value for key, value in data.items() if key != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def parse_licence(raw: bytes) -> LicenceDocument:
    """Parse and validate a licence file's bytes. Raises LicenceRejectedError on any problem."""
    if len(raw) > MAX_LICENCE_BYTES:
        raise LicenceRejectedError(reason="licence_malformed", detail="file too large")
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LicenceRejectedError(reason="licence_malformed", detail="not JSON") from exc
    if not isinstance(data, dict):
        raise LicenceRejectedError(reason="licence_malformed", detail="not a JSON object")
    try:
        entitlement = _entitlement(data)
        licence_id = _text(data, "licence_id")
        customer = _text(data, "customer")
    except (KeyError, TypeError, ValueError) as exc:
        raise LicenceRejectedError(reason="licence_malformed", detail=str(exc)) from exc
    signature = data.get("signature")
    if signature is not None and not isinstance(signature, str):
        raise LicenceRejectedError(reason="licence_malformed", detail="signature must be a string")
    fingerprint = data.get("fingerprint")
    installation_id = data.get("installation_id")
    return LicenceDocument(
        licence_id=licence_id,
        customer=customer,
        installation_id=str(installation_id) if installation_id is not None else None,
        fingerprint=fingerprint if isinstance(fingerprint, dict) else None,
        entitlement=entitlement,
        signature=signature or None,
        signed_payload=signed_payload(data),
    )


def _text(data: Mapping[str, Any], key: str) -> str:
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        msg = f"{key} must be a non-empty string"
        raise ValueError(msg)
    return value


def _day_start(value: str) -> datetime:
    return datetime.combine(date.fromisoformat(value), time.min, tzinfo=UTC)


def _day_end(value: str | None) -> datetime | None:
    # Valid through the whole named day.
    return None if value is None else _day_start(value) + timedelta(days=1)


def _entitlement(data: Mapping[str, Any]) -> Entitlement:
    grace_days = int(data.get("grace_days", DEFAULT_GRACE_DAYS))
    if not 0 <= grace_days <= MAX_GRACE_DAYS:
        msg = f"grace_days must be between 0 and {MAX_GRACE_DAYS}"
        raise ValueError(msg)
    limits = data.get("limits") or {}
    if not isinstance(limits, dict):
        msg = "limits must be an object"
        raise TypeError(msg)
    overrides: dict[LimitKey, int | None] = {}
    for key, value in limits.items():
        if value is not None and (not isinstance(value, int) or value < 0):
            msg = f"limit {key} must be a non-negative integer or null"
            raise ValueError(msg)
        overrides[LimitKey(key)] = value
    return Entitlement.build(
        Edition(data["edition"]),
        term=Term(
            starts_at=_day_start(data["issued_at"]),
            expires_at=_day_end(data.get("expires_at")),
            maintenance_until=_day_end(data.get("maintenance_until")),
            grace_days=grace_days,
        ),
        extra_features=frozenset(Feature(f) for f in data.get("features") or ()),
        limit_overrides=overrides,
    )
