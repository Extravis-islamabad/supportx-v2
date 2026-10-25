"""The integrity rules without I/O: canonical form, hashes, chain checks, signatures (ADR-027).

The golden values pin the byte layout shared with the database function `audit_seal()` and the
offline verifier; changing them breaks every chain already written.
"""

import base64
import hashlib
import random
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from app.modules.audit.domain.catalogue import ACTIONS, AuditCategory
from app.modules.audit.domain.integrity import (
    GENESIS_HASH,
    CanonicalError,
    ChainCheck,
    ChainLink,
    Problem,
    anchor_message,
    canonical,
    chain_hash,
    check_anchor,
    commitment,
    entry_content,
    entry_hash,
    format_time,
)
from app.modules.audit.infra.signing import (
    KeyConfigError,
    LocalSigner,
    new_key_config,
    signature_valid,
    trusted_keys,
)

TENANT = uuid.UUID("018f0000-0000-7000-8000-000000000001")
WHEN = datetime(2026, 10, 24, 12, 30, 45, 123456, tzinfo=UTC)


def entry(seq: int, **values: Any) -> dict[str, Any]:  # noqa: ANN401 - row values
    row: dict[str, Any] = {
        "id": uuid.UUID(int=seq),
        "tenant_id": TENANT,
        "occurred_at": WHEN + timedelta(seconds=seq),
        "action": "role.updated",
        "category": "access",
        "module": "identity_access",
        "outcome": "done",
        "reason_code": None,
        "actor_type": "person",
        "actor_id": uuid.UUID(int=1000),
        "on_behalf_id": None,
        "object_type": "role",
        "object_id": "r1",
        "details": {"grants_added": ["roles.view:all"], "count": seq},
        "client": "console",
        "request_id": f"req-{seq}",
        "change_id": None,
        "personal_commitments": {},
    }
    row.update(values)
    row["entry_hash"] = entry_hash(row)
    return row


def chain(rows: list[dict[str, Any]]) -> list[ChainLink]:
    links: list[ChainLink] = []
    previous = GENESIS_HASH
    for seq, row in enumerate(rows, start=1):
        link_hash = chain_hash(TENANT, seq, previous, row["entry_hash"])
        links.append(ChainLink(seq, row["id"], row["entry_hash"], previous, link_hash, row, {}))
        previous = link_hash
    return links


def run(links: list[ChainLink]) -> ChainCheck:
    check = ChainCheck.from_start(TENANT)
    for link in links:
        if not check.feed(link):
            break
    return check


# --- canonical form and golden values -----------------------------------------------------------


def test_canonical_sorts_keys_and_drops_whitespace() -> None:
    assert canonical({"b": 1, "a": [True, None, "x"]}) == b'{"a":[true,null,"x"],"b":1}'


def test_canonical_keeps_unicode_as_utf8() -> None:
    assert canonical({"name": "مدقق"}) == '{"name":"مدقق"}'.encode()


def test_times_are_utc_with_microseconds() -> None:
    karachi = timezone(timedelta(hours=5))
    assert format_time(WHEN.astimezone(karachi)) == "2026-10-24T12:30:45.123456Z"


@pytest.mark.parametrize("bad", [1.5, {"x": float("nan")}, {1: "key"}, object()])
def test_floats_odd_keys_and_unknown_types_are_refused(bad: Any) -> None:  # noqa: ANN401 - any input
    with pytest.raises(CanonicalError):
        canonical(bad)


def test_naive_times_are_refused() -> None:
    with pytest.raises(CanonicalError):
        canonical({"at": datetime(2026, 1, 1)})  # noqa: DTZ001 - the point of the test


def test_golden_entry_hash() -> None:
    assert entry_hash(entry(1)).hex() == (
        hashlib.sha256(
            b'{"action":"role.updated","actor_id":"00000000-0000-0000-0000-0000000003e8",'
            b'"actor_type":"person","category":"access","change_id":null,"client":"console",'
            b'"details":{"count":1,"grants_added":["roles.view:all"]},'
            b'"id":"00000000-0000-0000-0000-000000000001","module":"identity_access",'
            b'"object_id":"r1","object_type":"role","occurred_at":"2026-10-24T12:30:46.123456Z",'
            b'"on_behalf_id":null,"outcome":"done","personal_commitments":{},"reason_code":null,'
            b'"request_id":"req-1","tenant_id":"018f0000-0000-7000-8000-000000000001"}'
        ).hexdigest()
    )


def test_golden_chain_hash_layout() -> None:
    entry_digest = bytes(range(32))
    expected = hashlib.sha256(
        b"sx-audit-v1" + TENANT.bytes + (7).to_bytes(8, "big") + GENESIS_HASH + entry_digest
    ).digest()
    assert chain_hash(TENANT, 7, GENESIS_HASH, entry_digest) == expected


def test_chain_hash_needs_32_byte_hashes() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        chain_hash(TENANT, 1, b"short", bytes(32))


# --- chain checks (REQ-AUD-001) ----------------------------------------------------------------


def test_a_clean_chain_verifies() -> None:
    check = run(chain([entry(i) for i in range(1, 51)]))
    assert check.finding is None
    assert check.checked == 50


def test_changing_an_entry_is_found_and_named() -> None:
    links = chain([entry(i) for i in range(1, 11)])
    tampered = dict(links[4].entry or {})
    tampered["details"] = {"grants_added": ["users.manage:all"], "count": 5}
    links[4] = ChainLink(*links[4].__dict__.values())  # same link, replaced entry below
    links[4] = ChainLink(
        links[4].seq,
        links[4].entry_id,
        links[4].entry_hash,
        links[4].prev_hash,
        links[4].chain_hash,
        tampered,
        {},
    )
    finding = run(links).finding
    assert finding is not None
    assert (finding.seq, finding.entry_id, finding.problem) == (
        5,
        uuid.UUID(int=5),
        Problem.ENTRY_CHANGED,
    )


def test_changing_an_entry_and_its_stored_hash_is_still_found() -> None:
    links = chain([entry(i) for i in range(1, 6)])
    forged = entry(3, outcome="refused")  # a consistent row with a fresh entry hash
    links[2] = ChainLink(
        3, forged["id"], links[2].entry_hash, links[2].prev_hash, links[2].chain_hash, forged, {}
    )
    finding = run(links).finding
    assert finding is not None
    assert finding.problem is Problem.ENTRY_CHANGED


def test_rewriting_one_link_breaks_the_next() -> None:
    rows = [entry(i) for i in range(1, 6)]
    links = chain(rows)
    forged = entry(3, outcome="refused")
    new_hash = chain_hash(TENANT, 3, links[1].chain_hash, forged["entry_hash"])
    links[2] = ChainLink(
        3, forged["id"], forged["entry_hash"], links[1].chain_hash, new_hash, forged, {}
    )
    finding = run(links).finding
    assert finding is not None
    assert (finding.seq, finding.problem) == (4, Problem.CHAIN_BROKEN)


def test_a_removed_link_is_a_gap() -> None:
    links = chain([entry(i) for i in range(1, 6)])
    del links[2]
    finding = run(links).finding
    assert finding is not None
    assert (finding.seq, finding.problem) == (4, Problem.SEQUENCE_GAP)


def test_a_removed_entry_is_missing() -> None:
    links = chain([entry(i) for i in range(1, 4)])
    gone = links[1]
    links[1] = ChainLink(
        gone.seq, gone.entry_id, gone.entry_hash, gone.prev_hash, gone.chain_hash, None, {}
    )
    finding = run(links).finding
    assert finding is not None
    assert finding.problem is Problem.ENTRY_MISSING


def test_random_tampering_is_always_detected() -> None:
    rng = random.Random(18)  # noqa: S311 - deterministic test data, not security
    fields = ["action", "outcome", "actor_id", "object_id", "details", "request_id", "occurred_at"]
    for _ in range(200):
        rows = [entry(i) for i in range(1, 21)]
        links = chain(rows)
        position = rng.randrange(20)
        field = rng.choice(fields)
        changed = dict(rows[position])
        changed[field] = (
            WHEN - timedelta(days=1)
            if field == "occurred_at"
            else ({"x": 1} if field == "details" else f"forged-{field}")
        )
        old = links[position]
        links[position] = ChainLink(
            old.seq, old.entry_id, old.entry_hash, old.prev_hash, old.chain_hash, changed, {}
        )
        finding = run(links).finding
        assert finding is not None
        assert finding.seq == position + 1, field


# --- personal data (REQ-AUD-013) -----------------------------------------------------------------


def test_personal_data_is_committed_not_hashed_in_clear() -> None:
    salt = bytes(16)
    data = {"ip": "10.1.2.3", "user_agent": "Firefox"}
    person = str(uuid.UUID(int=1000))
    row = entry(1, personal_commitments={person: commitment(salt, data)})
    assert b"10.1.2.3" not in canonical(entry_content(row))
    links = chain([row])
    with_personal = ChainLink(*[*list(links[0].__dict__.values())[:-1], {person: (salt, data)}])
    assert run([with_personal]).finding is None
    # Erased: the personal row is gone, the chain still verifies.
    assert run(links).finding is None
    # Changed: the commitment no longer matches.
    changed = ChainLink(
        *[*list(links[0].__dict__.values())[:-1], {person: (salt, {"ip": "1.1.1.1"})}]
    )
    finding = run([changed]).finding
    assert finding is not None
    assert finding.problem is Problem.PERSONAL_CHANGED


# --- anchors and keys ---------------------------------------------------------------------------


def test_anchor_checks() -> None:
    hashes = {1: b"a" * 32, 2: b"b" * 32}
    assert check_anchor(hashes, 2, b"b" * 32, last_seq=2) is None
    assert check_anchor(hashes, 2, b"x" * 32, last_seq=2) is Problem.ANCHOR_MISMATCH
    assert check_anchor(hashes, 5, b"b" * 32, last_seq=2) is Problem.ANCHOR_BEYOND_CHAIN


def test_signing_and_rotation() -> None:
    old = LocalSigner.from_config(new_key_config("k2026a"))
    new = LocalSigner.from_config(new_key_config("k2026b"))
    message = anchor_message(TENANT, 10, b"c" * 32, WHEN)
    signature = old.sign(message)
    assert signature_valid(old.public_key, message, signature)
    assert not signature_valid(new.public_key, message, signature)
    retired = f"{old.key_id}:{base64.b64encode(old.public_key).decode()}"
    keys = trusted_keys(retired, new)
    assert keys == {"k2026a": old.public_key, "k2026b": new.public_key}


@pytest.mark.parametrize(
    "value", ["nokey", "k1:not-base64!", "k1:" + base64.b64encode(b"short").decode()]
)
def test_bad_key_configuration_is_refused_without_echoing_it(value: str) -> None:
    with pytest.raises(KeyConfigError) as raised:
        LocalSigner.from_config(value)
    assert "not-base64!" not in str(raised.value)


def test_every_action_belongs_to_a_category() -> None:
    assert all(isinstance(spec.category, AuditCategory) for spec in ACTIONS.values())
    assert all(code == spec.code for code, spec in ACTIONS.items())
