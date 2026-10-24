"""The integrity rules of the audit log: canonical form, hashes, chain and commitments (ADR-027).

Pure functions, no I/O. The same byte layout is computed in three places and must never drift:

* here (the service records `entry_hash` and verifies chains);
* the database function `audit_seal()` (migration 0013), which writes the chain;
* the standalone offline verifier `tools/audit-verify/verify_export.py` (standard library only).

Golden tests pin all three to the same bytes.

Entry hash
    SHA-256 of the canonical JSON of the entry's content (`ENTRY_FIELDS`). Canonical JSON: keys
    sorted, no whitespace, UTF-8, strings and integers only (no floats), times as
    `YYYY-MM-DDTHH:MM:SS.ffffffZ` in UTC, UUIDs as lowercase strings.

Chain hash
    `SHA-256(b"sx-audit-v1" ‖ tenant UUID (16 bytes) ‖ seq (8 bytes, big-endian) ‖ previous chain
    hash ‖ entry hash)`. The first entry's previous hash is 32 zero bytes. Changing, removing or
    inserting any entry changes every later chain hash.

Personal data (REQ-AUD-013)
    IP addresses, user agents and free text never enter the hashed content. They are stored per
    data subject with a random salt; the entry holds only `SHA-256(salt ‖ canonical(data))` per
    subject (`personal_commitments`). Erasing a subject deletes their rows; the chain still
    verifies, and the commitments of everyone else can still be checked.
"""

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

DOMAIN_TAG = b"sx-audit-v1"
HASH_SIZE = 32
GENESIS_HASH = bytes(HASH_SIZE)
SALT_SIZE = 16

# The entry's content, hashed in this exact set (order does not matter: keys are sorted).
ENTRY_FIELDS: tuple[str, ...] = (
    "id",
    "tenant_id",
    "occurred_at",
    "action",
    "category",
    "module",
    "outcome",
    "reason_code",
    "actor_type",
    "actor_id",
    "on_behalf_id",
    "object_type",
    "object_id",
    "details",
    "client",
    "request_id",
    "change_id",
    "personal_commitments",
)


class CanonicalError(ValueError):
    """A value cannot be put in canonical form (a float, an unknown type, a non-string key)."""


def format_time(value: datetime) -> str:
    """UTC, microseconds, `Z`: the one time format inside hashed content."""
    if value.tzinfo is None:
        msg = "naive datetime in audit content"
        raise CanonicalError(msg)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def plain(value: Any) -> Any:  # noqa: ANN401, C901, PLR0911 - any JSON-like input; one branch per type
    """`value` as plain JSON types (UUIDs, times and enums as strings); floats are refused."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # Floats have several valid encodings; the verifier in another language must not guess.
        msg = "floats are not allowed in audit content; use integers or strings"
        raise CanonicalError(msg)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return format_time(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                msg = "audit content keys must be strings"
                raise CanonicalError(msg)
            out[key] = plain(item)
        return out
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    msg = f"cannot put {type(value).__name__} in audit content"
    raise CanonicalError(msg)


def canonical(value: Any) -> bytes:  # noqa: ANN401 - any JSON-like input
    """Canonical JSON bytes of `value`."""
    return json.dumps(
        plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def entry_content(row: Mapping[str, Any]) -> dict[str, Any]:
    """The hashed part of an entry row, normalised (missing optional fields become null)."""
    content = {name: row.get(name) for name in ENTRY_FIELDS}
    content["details"] = content["details"] or {}
    content["personal_commitments"] = content["personal_commitments"] or {}
    return plain(content)  # type: ignore[no-any-return]  # a dict in, a dict out


def entry_hash(row: Mapping[str, Any]) -> bytes:
    """SHA-256 of the canonical entry content."""
    return hashlib.sha256(canonical(entry_content(row))).digest()


def chain_hash(tenant_id: uuid.UUID, seq: int, previous: bytes, entry: bytes) -> bytes:
    """The chain link for position `seq` (see the module docstring)."""
    if len(previous) != HASH_SIZE or len(entry) != HASH_SIZE:
        msg = "hashes must be 32 bytes"
        raise ValueError(msg)
    return hashlib.sha256(
        DOMAIN_TAG + tenant_id.bytes + seq.to_bytes(8, "big", signed=True) + previous + entry
    ).digest()


def commitment(salt: bytes, data: Mapping[str, Any]) -> str:
    """Hex commitment to one subject's personal data in one entry."""
    return hashlib.sha256(salt + canonical(data)).hexdigest()


# --- verification -----------------------------------------------------------------------------


class Problem(StrEnum):
    """Why verification failed at an entry (labels: `audit.problem.<code>`)."""

    ENTRY_CHANGED = "entry_changed"  # content no longer matches its recorded hash
    ENTRY_MISSING = "entry_missing"  # a chain link points to an entry that is gone
    SEQUENCE_GAP = "sequence_gap"  # a position in the chain is missing
    CHAIN_BROKEN = "chain_broken"  # a link does not follow from the previous one
    PERSONAL_CHANGED = "personal_changed"  # personal data no longer matches its commitment
    ANCHOR_MISMATCH = "anchor_mismatch"  # an anchor names a hash the chain no longer has
    ANCHOR_SIGNATURE = "anchor_signature"  # an anchor's signature or key is not trusted
    ANCHOR_BEYOND_CHAIN = "anchor_beyond_chain"  # entries after an anchor were removed


@dataclass(frozen=True)
class ChainLink:
    """One stored chain row, with the entry it seals (None if the entry is gone)."""

    seq: int
    entry_id: uuid.UUID
    entry_hash: bytes
    prev_hash: bytes
    chain_hash: bytes
    entry: Mapping[str, Any] | None
    personal: Mapping[str, tuple[bytes, Mapping[str, Any]]]  # subject id -> (salt, data)


@dataclass(frozen=True)
class Finding:
    """The first problem found, or None when the range is clean."""

    seq: int
    entry_id: uuid.UUID | None
    problem: Problem


@dataclass
class ChainCheck:
    """Incremental verifier: feed links in `seq` order; it keeps only the previous hash."""

    tenant_id: uuid.UUID
    expected_seq: int
    previous: bytes
    checked: int = 0
    finding: Finding | None = None

    @classmethod
    def from_start(cls, tenant_id: uuid.UUID) -> "ChainCheck":
        """Verification of a whole chain, from its genesis."""
        return cls(tenant_id, 1, GENESIS_HASH)

    def feed(self, link: ChainLink) -> bool:
        """Check one link; False (and `finding` set) at the first problem."""
        if self.finding is not None:
            return False
        problem = self._problem(link)
        if problem is not None:
            self.finding = Finding(link.seq, link.entry_id, problem)
            return False
        self.previous = link.chain_hash
        self.expected_seq = link.seq + 1
        self.checked += 1
        return True

    def _problem(self, link: ChainLink) -> Problem | None:  # noqa: PLR0911 - one return per rule, in order
        if link.seq != self.expected_seq:
            return Problem.SEQUENCE_GAP
        if link.prev_hash != self.previous:
            return Problem.CHAIN_BROKEN
        if chain_hash(self.tenant_id, link.seq, link.prev_hash, link.entry_hash) != link.chain_hash:
            return Problem.CHAIN_BROKEN
        if link.entry is None:
            return Problem.ENTRY_MISSING
        if entry_hash(link.entry) != link.entry_hash:
            return Problem.ENTRY_CHANGED
        if bytes(link.entry["entry_hash"]) != link.entry_hash:
            return Problem.ENTRY_CHANGED
        commitments: Mapping[str, str] = link.entry.get("personal_commitments") or {}
        for subject, (salt, data) in link.personal.items():
            if commitments.get(subject) != commitment(salt, data):
                return Problem.PERSONAL_CHANGED
        return None


def check_anchor(
    links_by_seq: Mapping[int, bytes], anchor_seq: int, anchor_hash: bytes, last_seq: int
) -> Problem | None:
    """Compare an anchor with the chain: the hash must still be there at its position."""
    if anchor_seq > last_seq:
        return Problem.ANCHOR_BEYOND_CHAIN
    stored = links_by_seq.get(anchor_seq)
    if stored is not None and stored != anchor_hash:
        return Problem.ANCHOR_MISMATCH
    return None


def anchor_message(tenant_id: uuid.UUID, seq: int, chain: bytes, created_at: datetime) -> bytes:
    """The bytes an anchor signature covers."""
    return canonical(
        {
            "tenant_id": tenant_id,
            "seq": seq,
            "chain_hash": chain.hex(),
            "created_at": created_at,
            "v": 1,
        }
    )


def personal_rows(
    rows: Iterable[tuple[uuid.UUID, bytes, Mapping[str, Any]]],
) -> dict[str, tuple[bytes, Mapping[str, Any]]]:
    """(subject id, salt, data) rows → the `personal` mapping of a ChainLink."""
    return {str(subject): (bytes(salt), data) for subject, salt, data in rows}
