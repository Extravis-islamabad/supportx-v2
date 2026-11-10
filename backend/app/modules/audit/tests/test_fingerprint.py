"""The change-set fingerprint without I/O (WP-064 S2, D-150, ADR-046).

The golden vector pins the byte layout ADR-046 specifies: a verifier written later, in any
language, must reproduce exactly these digests. Changing a value here breaks every fingerprint
already in a chain; a new layout gets a new prefix instead.
"""

import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest

from app.modules.audit.domain.fingerprint import (
    PREFIX,
    FieldValues,
    FingerprintError,
    FingerprintStatus,
    SaveValues,
    canonical_value,
    change_set,
    fingerprint,
    status_of,
    value_digest,
)
from app.modules.audit.domain.integrity import entry_hash
from app.modules.audit.domain.lifecycle import ASSET, RECORD_TYPES
from app.modules.audit.tests.test_integrity import entry

RECORD = uuid.UUID("0190a000-0000-7000-8000-000000000001")
SAVE_1 = uuid.UUID("0190a000-0000-7000-8000-0000000000c1")
SAVE_2 = uuid.UUID("0190a000-0000-7000-8000-0000000000c2")
ALICE = uuid.UUID("0190a000-0000-7000-8000-00000000000a")
BILAL = uuid.UUID("0190a000-0000-7000-8000-00000000000b")
SALTS = {ALICE: bytes(range(16)), BILAL: bytes(range(16, 32))}
SAVES = [
    SaveValues(
        SAVE_1,
        1,
        "created",
        (
            FieldValues("subject", None, 'Printer "P-3" jams\n', personal=True),
            FieldValues("priority", None, "p2"),
            FieldValues("custom.cost", None, 1.0),
            FieldValues("custom.ratio", None, 1.5e-7),
        ),
    ),
    SaveValues(
        SAVE_2,
        2,
        "updated",
        (
            FieldValues("tags", ["a"], ["a", "b"]),
            FieldValues("description", "قديم", {"z": 1, "a": [True, False, None]}, personal=True),
            FieldValues("technician_id", None, "0190a000-0000-7000-8000-0000000000ff"),
        ),
    ),
]
NULL = "74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b"  # SHA-256("null")
GOLDEN = "fp1:f27b292b6b9a3063d3ee32b318c7215b3aa4df90693a55d1dd3c230f7d1ea66d"


# --- the golden vector (also in docs/adr/ADR-046) -----------------------------------------------


def test_golden_vector() -> None:
    assert fingerprint("work_item", RECORD, SAVES, [BILAL, ALICE], SALTS) == GOLDEN


def test_golden_vector_layout_recomputed_by_hand() -> None:
    """The same digest from first principles: only hashlib and the rules written in ADR-046."""

    def h(value: bytes, *salts: bytes) -> str:
        return hashlib.sha256(b"".join(salts) + value).hexdigest()

    a, b = SALTS[ALICE], SALTS[BILAL]
    people = '["0190a000-0000-7000-8000-00000000000a","0190a000-0000-7000-8000-00000000000b"]'
    text = (
        '{"record_id":"0190a000-0000-7000-8000-000000000001","record_type":"work_item",'
        '"saves":[{"change_id":"0190a000-0000-7000-8000-0000000000c1","fields":['
        f'["custom.cost","{NULL}","{h(b"1")}",[]],'
        f'["custom.ratio","{NULL}","{h(b"0.00000015")}",[]],'
        f'["priority","{NULL}","{h(b'"p2"')}",[]],'
        f'["subject","{h(b"null", a, b)}","{h(b'"Printer \\"P-3\\" jams\\n"', a, b)}",{people}]'
        '],"kind":"created","version":1},'
        '{"change_id":"0190a000-0000-7000-8000-0000000000c2","fields":['
        f'["description","{h('"قديم"'.encode(), a, b)}",'
        f'"{h(b'{"a":[true,false,null],"z":1}', a, b)}",{people}],'
        f'["tags","{h(b'["a"]')}","{h(b'["a","b"]')}",[]],'
        f'["technician_id","{NULL}","{h(b'"0190a000-0000-7000-8000-0000000000ff"')}",[]]'
        '],"kind":"updated","version":2}],"v":1}'
    )
    assert canonical_value(change_set("work_item", RECORD, SAVES, [ALICE, BILAL], SALTS)) == (
        text.encode()
    )
    assert PREFIX + hashlib.sha256(text.encode()).hexdigest() == GOLDEN


# --- canonical values -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, b"null"),
        (True, b"true"),
        (False, b"false"),
        (1, b"1"),
        (1.0, b"1"),  # a number is its value: JSONB may hand back 1.0 or 1
        (-0.0, b"0"),
        (1e20, b"100000000000000000000"),
        (1.5e-7, b"0.00000015"),
        (0.1, b"0.1"),
        (-2.50, b"-2.5"),
        ('a"\\\n\x01\x7fé', '"a\\"\\\\\\n\\u0001\x7fé"'.encode()),
        ({"b": 1, "a": 2, "ä": 3, "Z": 4}, '{"Z":4,"a":2,"b":1,"ä":3}'.encode()),
        ([1, "x", [None]], b'[1,"x",[null]]'),
        ((1, 2), b"[1,2]"),
        (
            uuid.UUID("0190A000-0000-7000-8000-0000000000FF"),
            b'"0190a000-0000-7000-8000-0000000000ff"',
        ),
        (date(2026, 11, 11), b'"2026-11-11"'),
        (
            datetime(2026, 11, 11, 15, 0, tzinfo=timezone(timedelta(hours=5))),
            b'"2026-11-11T10:00:00.000000Z"',
        ),
    ],
)
def test_canonical_values(value: Any, expected: bytes) -> None:  # noqa: ANN401 - any input
    assert canonical_value(value) == expected


def test_a_value_hashes_the_same_before_and_after_jsonb() -> None:
    """The save hashes the value it wrote; the verifier hashes what JSONB hands back."""
    for value in (1.0, 1e20, 1.5e-7, {"b": [1.25, "x"], "a": None}, "Ünïcödé"):
        assert value_digest(value) == value_digest(json.loads(json.dumps(value)))
    assert value_digest(1e20) == value_digest(100000000000000000000)  # JSONB drops the exponent


NAIVE = datetime(2026, 1, 1)  # noqa: DTZ001 - a naive time is refused: the point of the test


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), {1: "x"}, object(), NAIVE])
def test_values_without_one_canonical_form_are_refused(bad: Any) -> None:  # noqa: ANN401 - any input
    with pytest.raises(FingerprintError):
        canonical_value(bad)


def test_a_string_and_a_number_never_collide() -> None:
    assert value_digest("1") != value_digest(1)
    assert value_digest(None) == NULL


# --- what the fingerprint covers --------------------------------------------------------------


def test_every_part_of_a_save_changes_the_fingerprint() -> None:
    def fp(saves: list[SaveValues], record: uuid.UUID = RECORD) -> str:
        return fingerprint("work_item", record, saves, [ALICE, BILAL], SALTS)

    first, second = SAVES
    variants = [
        [first],  # a save removed
        [second, first],  # saves reordered
        [SaveValues(SAVE_1, 9, first.kind, first.fields), second],  # the version
        [SaveValues(SAVE_1, 1, "updated", first.fields), second],  # the kind
        [SaveValues(SAVE_1, 1, "created", first.fields[1:]), second],  # a field removed
        [
            SaveValues(
                SAVE_1, 1, "created", (FieldValues("priority", None, "p1"), *first.fields[1:])
            ),
            second,
        ],  # a value
    ]
    assert len({fp(v) for v in variants} | {GOLDEN}) == len(variants) + 1
    assert fp(SAVES, uuid.uuid4()) != GOLDEN  # another record
    assert fingerprint("asset", RECORD, SAVES, [ALICE, BILAL], SALTS) != GOLDEN
    # Field order within a save does not matter (history stores no order); save order does.
    shuffled = SaveValues(SAVE_1, 1, "created", tuple(reversed(first.fields)))
    assert fp([shuffled, second]) == GOLDEN


def test_personal_values_need_the_salts_and_ordinary_ones_do_not() -> None:
    other = {ALICE: bytes(16), BILAL: SALTS[BILAL]}
    assert fingerprint("work_item", RECORD, SAVES, [ALICE, BILAL], other) != GOLDEN
    ordinary = [SaveValues(SAVE_1, 1, "created", (FieldValues("priority", None, "p2"),))]
    assert fingerprint("work_item", RECORD, ordinary, [ALICE, BILAL], other) == fingerprint(
        "work_item", RECORD, ordinary, [ALICE, BILAL], SALTS
    )
    with pytest.raises(KeyError):  # a subject without a salt is a caller bug, never a guess
        fingerprint("work_item", RECORD, SAVES, [ALICE, BILAL], {ALICE: SALTS[ALICE]})


def test_the_change_set_holds_digests_never_values() -> None:
    content = canonical_value(change_set("work_item", RECORD, SAVES, [ALICE, BILAL], SALTS))
    for secret in ("Printer", "P-3", "قديم", "p2"):
        assert secret.encode() not in content


# --- verdicts ---------------------------------------------------------------------------------

AT = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)


def test_verdicts() -> None:
    def verdict(
        recomputed: str | None, salted: list[uuid.UUID], erased: dict[uuid.UUID, datetime]
    ) -> FingerprintStatus:
        return status_of(
            GOLDEN,
            recomputed,
            subjects=[ALICE, BILAL],
            salted=salted,
            erased_after=erased,
            occurred_at=AT,
        )

    later, earlier = AT + timedelta(days=1), AT - timedelta(days=1)
    assert verdict(GOLDEN, [ALICE, BILAL], {}) is FingerprintStatus.VERIFIED
    assert verdict("fp1:" + "0" * 64, [ALICE, BILAL], {}) is FingerprintStatus.MISMATCH
    assert verdict(None, [ALICE, BILAL], {}) is FingerprintStatus.MISMATCH
    # A salt is gone: accepted only with the subject's logged erasure after the entry.
    assert verdict(None, [BILAL], {ALICE: later}) is FingerprintStatus.ERASED_ON_REQUEST
    assert verdict(None, [BILAL], {}) is FingerprintStatus.MISMATCH
    assert verdict(None, [BILAL], {ALICE: earlier}) is FingerprintStatus.MISMATCH
    assert verdict(None, [], {ALICE: later}) is FingerprintStatus.MISMATCH  # Bilal not erased
    assert verdict(None, [], {ALICE: later, BILAL: later}) is FingerprintStatus.ERASED_ON_REQUEST


# --- the entry hash ---------------------------------------------------------------------------


def test_older_entries_hash_exactly_as_before() -> None:
    old = entry(1)
    assert entry_hash({**old, "fingerprint": None, "fingerprint_saves": None}) == old["entry_hash"]


def test_the_fingerprint_its_saves_and_subjects_are_inside_the_entry_hash() -> None:
    base = entry(1, fingerprint=GOLDEN, fingerprint_saves=[SAVE_1], personal_subjects=[ALICE])
    assert base["entry_hash"] != entry(1)["entry_hash"]
    changes: tuple[dict[str, Any], ...] = (
        {"fingerprint": "fp1:" + "0" * 64},
        {"fingerprint_saves": [SAVE_2]},
        {"personal_subjects": [BILAL]},
        {"personal_subjects": []},
    )
    for change in changes:
        assert entry_hash({**base, **change}) != base["entry_hash"]


# --- the personal-field lists -----------------------------------------------------------------


def test_the_personal_fields_of_each_type() -> None:
    incident, change = RECORD_TYPES["incident"], RECORD_TYPES["change"]
    for name in ("subject", "description", "resolution", "custom.notes", "task"):
        assert incident.is_personal(name)
    for name in ("requester_id", "status", "priority", "technician_id", "task.status"):
        assert not incident.is_personal(name)  # IDs and codes are never personal
    assert change.is_personal("plan.backout")
    assert change.is_personal("schedule.implementation.outcome_notes")
    assert not change.is_personal("schedule.implementation.scheduled_start")
    assert RECORD_TYPES["problem"].is_personal("root_cause")
    assert not incident.is_personal("root_cause")
    assert ASSET.personal == ()
    assert all(
        spec.data_subjects == ("requester_id", "on_behalf_of_id")
        and spec.history_record_type == "work_item"
        for code, spec in RECORD_TYPES.items()
        if code != "asset"
    )
