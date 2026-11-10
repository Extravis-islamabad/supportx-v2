"""The change-set fingerprints without I/O (WP-064 S2, D-150, ADR-046).

The golden vectors pin the byte layout ADR-046 specifies: a verifier written later, in any
language, must reproduce exactly these digests. Changing a value here breaks every fingerprint
already in a chain; a new layout gets a new prefix instead.

Two commitments per save entry: `fingerprint` over the ordinary fields (no salt, so it always
recomputes) and `personal_fingerprint` over the personal fields (salted). Vector A is a save
with ordinary fields only; vector B has both.
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
    personal_fingerprint,
    status_of,
    value_digest,
)
from app.modules.audit.domain.integrity import entry_hash
from app.modules.audit.domain.lifecycle import ASSET, RECORD_TYPES
from app.modules.audit.tests.test_integrity import entry

RECORD = uuid.UUID("0190a000-0000-7000-8000-000000000001")
SAVE_1 = uuid.UUID("0190a000-0000-7000-8000-0000000000c1")
SAVE_2 = uuid.UUID("0190a000-0000-7000-8000-0000000000c2")
SAVE_3 = uuid.UUID("0190a000-0000-7000-8000-0000000000c3")
ALICE = uuid.UUID("0190a000-0000-7000-8000-00000000000a")
BILAL = uuid.UUID("0190a000-0000-7000-8000-00000000000b")
SALTS = {ALICE: bytes(range(16)), BILAL: bytes(range(16, 32))}
# Vector A: one save, ordinary fields only.
ORDINARY_ONLY = [
    SaveValues(
        SAVE_3,
        4,
        "updated",
        (
            FieldValues("priority", "p3", "p2"),
            FieldValues("custom.cost", None, 1.0),
            FieldValues("custom.ratio", None, 1.5e-7),
            FieldValues("tags", ["a"], ["a", "b"]),
        ),
    )
]
# Vector B: two saves, each with an ordinary and a personal field.
SAVES = [
    SaveValues(
        SAVE_1,
        1,
        "created",
        (
            FieldValues("subject", None, 'Printer "P-3" jams\n', personal=True),
            FieldValues("priority", None, "p2"),
        ),
    ),
    SaveValues(
        SAVE_2,
        2,
        "updated",
        (
            FieldValues("description", "قديم", {"z": 1, "a": [True, False, None]}, personal=True),
            FieldValues("technician_id", None, "0190a000-0000-7000-8000-0000000000ff"),
        ),
    ),
]
NULL = "74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b"  # SHA-256("null")
GOLDEN_A = "fp1:bb1da1530c996cd33f32d0ddcb06e5abee569db571995b72379a41b301a33e78"
GOLDEN_B = "fp1:929257682249c7d55f6eebe8a2e94f6c22d53980a5de35d75c7c6e1aa8bc631a"
GOLDEN_B_PERSONAL = "fp1:6d5e5a7fe00b3fcd987413b14fbd4e2d62b7dd41d238b01e910aae2a8dcee4fc"


def h(value: bytes, *salts: bytes) -> str:
    """A field digest from first principles."""
    return hashlib.sha256(b"".join(salts) + value).hexdigest()


def fp(text: str) -> str:
    """A fingerprint from first principles."""
    return PREFIX + hashlib.sha256(text.encode()).hexdigest()


# --- the golden vectors (also in docs/adr/ADR-046) ----------------------------------------------


def test_golden_vectors() -> None:
    assert fingerprint("work_item", RECORD, ORDINARY_ONLY) == GOLDEN_A
    assert personal_fingerprint("work_item", RECORD, ORDINARY_ONLY, [], {}) is None
    assert fingerprint("work_item", RECORD, SAVES) == GOLDEN_B
    assert personal_fingerprint("work_item", RECORD, SAVES, [BILAL, ALICE], SALTS) == (
        GOLDEN_B_PERSONAL
    )


def test_golden_vector_a_recomputed_by_hand() -> None:
    """Only hashlib and the rules written in ADR-046."""
    text = (
        '{"part":"ordinary","record_id":"0190a000-0000-7000-8000-000000000001",'
        '"record_type":"work_item","saves":[{"change_id":"0190a000-0000-7000-8000-0000000000c3",'
        f'"fields":[["custom.cost","{NULL}","{h(b"1")}"],'
        f'["custom.ratio","{NULL}","{h(b"0.00000015")}"],'
        f'["priority","{h(b'"p3"')}","{h(b'"p2"')}"],'
        f'["tags","{h(b'["a"]')}","{h(b'["a","b"]')}"]],'
        '"kind":"updated","version":4}],"v":1}'
    )
    assert canonical_value(change_set("work_item", RECORD, ORDINARY_ONLY)) == text.encode()
    assert fp(text) == GOLDEN_A


def test_golden_vector_b_recomputed_by_hand() -> None:
    """Both halves of vector B, only hashlib and the rules written in ADR-046."""
    a, b = SALTS[ALICE], SALTS[BILAL]
    people = '["0190a000-0000-7000-8000-00000000000a","0190a000-0000-7000-8000-00000000000b"]'
    record = '"record_id":"0190a000-0000-7000-8000-000000000001","record_type":"work_item"'
    first = '{"change_id":"0190a000-0000-7000-8000-0000000000c1","fields":['
    second = '{"change_id":"0190a000-0000-7000-8000-0000000000c2","fields":['
    ordinary = (
        f'{{"part":"ordinary",{record},"saves":[{first}'
        f'["priority","{NULL}","{h(b'"p2"')}"]'
        f'],"kind":"created","version":1}},{second}'
        f'["technician_id","{NULL}","{h(b'"0190a000-0000-7000-8000-0000000000ff"')}"]'
        '],"kind":"updated","version":2}],"v":1}'
    )
    personal = (
        f'{{"part":"personal",{record},"saves":[{first}'
        f'["subject","{h(b"null", a, b)}","{h(b'"Printer \\"P-3\\" jams\\n"', a, b)}",{people}]'
        f'],"kind":"created","version":1}},{second}'
        f'["description","{h('"قديم"'.encode(), a, b)}",'
        f'"{h(b'{"a":[true,false,null],"z":1}', a, b)}",{people}]'
        '],"kind":"updated","version":2}],"v":1}'
    )
    assert canonical_value(change_set("work_item", RECORD, SAVES)) == ordinary.encode()
    built = change_set("work_item", RECORD, SAVES, "personal", subjects=[ALICE, BILAL], salts=SALTS)
    assert canonical_value(built) == personal.encode()
    assert fp(ordinary) == GOLDEN_B
    assert fp(personal) == GOLDEN_B_PERSONAL


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


# --- what the fingerprints cover ------------------------------------------------------------


def _priority(value: str) -> FieldValues:
    return FieldValues("priority", None, value)


def _subject(value: str) -> FieldValues:
    return FieldValues("subject", None, value, personal=True)


def test_every_part_of_a_save_changes_the_ordinary_fingerprint() -> None:
    def ordinary(saves: list[SaveValues], record: uuid.UUID = RECORD) -> str:
        return fingerprint("work_item", record, saves)

    first, second = SAVES
    variants = [
        [first],  # a save removed
        [second, first],  # saves reordered
        [SaveValues(SAVE_1, 9, first.kind, first.fields), second],  # the version
        [SaveValues(SAVE_1, 1, "updated", first.fields), second],  # the kind
        [SaveValues(SAVE_1, 1, "created", first.fields[:1]), second],  # a field removed
        [
            SaveValues(SAVE_1, 1, "created", (first.fields[0], _priority("p1"))),
            second,
        ],  # a value
    ]
    assert len({ordinary(v) for v in variants} | {GOLDEN_B}) == len(variants) + 1
    assert ordinary(SAVES, uuid.uuid4()) != GOLDEN_B  # another record
    assert fingerprint("asset", RECORD, SAVES) != GOLDEN_B
    # Field order within a save does not matter (history stores no order); save order does.
    shuffled = SaveValues(SAVE_1, 1, "created", tuple(reversed(first.fields)))
    assert ordinary([shuffled, second]) == GOLDEN_B


def test_the_halves_are_independent() -> None:
    """A personal value never moves the ordinary half; an ordinary one never the personal."""
    first, second = SAVES
    personal_changed = [
        SaveValues(SAVE_1, 1, "created", (_subject("Other"), first.fields[1])),
        second,
    ]
    assert fingerprint("work_item", RECORD, personal_changed) == GOLDEN_B
    assert personal_fingerprint("work_item", RECORD, personal_changed, [ALICE, BILAL], SALTS) != (
        GOLDEN_B_PERSONAL
    )
    ordinary_changed = [
        SaveValues(SAVE_1, 1, "created", (first.fields[0], _priority("p1"))),
        second,
    ]
    assert fingerprint("work_item", RECORD, ordinary_changed) != GOLDEN_B
    assert personal_fingerprint("work_item", RECORD, ordinary_changed, [ALICE, BILAL], SALTS) == (
        GOLDEN_B_PERSONAL
    )


def test_only_the_personal_half_needs_the_salts() -> None:
    other = {ALICE: bytes(16), BILAL: SALTS[BILAL]}
    assert personal_fingerprint("work_item", RECORD, SAVES, [ALICE, BILAL], other) != (
        GOLDEN_B_PERSONAL
    )
    with pytest.raises(KeyError):  # a subject without a salt is a caller bug, never a guess
        personal_fingerprint("work_item", RECORD, SAVES, [ALICE, BILAL], {ALICE: SALTS[ALICE]})


def test_the_change_sets_hold_digests_never_values() -> None:
    for content in (
        canonical_value(change_set("work_item", RECORD, SAVES)),
        canonical_value(
            change_set("work_item", RECORD, SAVES, "personal", subjects=[ALICE], salts=SALTS)
        ),
    ):
        for secret in ("Printer", "P-3", "قديم", "p2"):
            assert secret.encode() not in content
    with pytest.raises(FingerprintError):
        change_set("work_item", RECORD, SAVES, "both")


# --- verdicts ---------------------------------------------------------------------------------

AT = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)
LATER, EARLIER = AT + timedelta(days=1), AT - timedelta(days=1)


def _verdict(
    *,
    ordinary: bool = True,
    recomputed: str | None = GOLDEN_B_PERSONAL,
    salted: tuple[uuid.UUID, ...] = (ALICE, BILAL),
    erased: dict[uuid.UUID, datetime] | None = None,
    stored: str | None = GOLDEN_B_PERSONAL,
    subjects: tuple[uuid.UUID, ...] = (ALICE, BILAL),
) -> FingerprintStatus:
    return status_of(
        ordinary_matches=ordinary,
        personal_stored=stored,
        personal_recomputed=recomputed,
        subjects=subjects,
        salted=salted,
        erased_after=erased or {},
        occurred_at=AT,
    )


def test_verdicts() -> None:
    verified, mismatch = FingerprintStatus.VERIFIED, FingerprintStatus.MISMATCH
    erased_on_request = FingerprintStatus.ERASED_ON_REQUEST
    assert _verdict() is verified
    assert _verdict(recomputed="fp1:" + "0" * 64) is mismatch
    assert _verdict(ordinary=False) is mismatch
    # No personal field: no personal fingerprint, and nothing to recompute.
    assert _verdict(stored=None, recomputed=None, subjects=(), salted=()) is verified
    assert _verdict(stored=None, recomputed=GOLDEN_B_PERSONAL) is mismatch  # one appeared
    # A salt is gone: accepted only with the subject's logged erasure after the entry ...
    assert _verdict(recomputed=None, salted=(BILAL,), erased={ALICE: LATER}) is erased_on_request
    assert _verdict(recomputed=None, salted=(BILAL,)) is mismatch
    assert _verdict(recomputed=None, salted=(BILAL,), erased={ALICE: EARLIER}) is mismatch
    assert _verdict(recomputed=None, salted=(), erased={ALICE: LATER}) is mismatch
    both = {ALICE: LATER, BILAL: LATER}
    assert _verdict(recomputed=None, salted=(), erased=both) is erased_on_request


def test_an_erasure_never_hides_a_changed_ordinary_value() -> None:
    """The attack: change an ordinary value, then erase the subject. Still a mismatch."""
    erased = {ALICE: LATER, BILAL: LATER}
    verdict = _verdict(ordinary=False, recomputed=None, salted=(), erased=erased)
    assert verdict is FingerprintStatus.MISMATCH


# --- the entry hash ---------------------------------------------------------------------------


def test_older_entries_hash_exactly_as_before() -> None:
    old = entry(1)
    assert entry_hash({**old, "fingerprint": None, "fingerprint_saves": None}) == old["entry_hash"]


def test_the_fingerprints_saves_and_subjects_are_inside_the_entry_hash() -> None:
    plain = entry(1, fingerprint=GOLDEN_A, fingerprint_saves=[SAVE_3], personal_subjects=[])
    # Without a personal half the key is absent: the same hash as with it set to null.
    assert entry_hash({**plain, "personal_fingerprint": None}) == plain["entry_hash"]
    assert entry_hash({**plain, "personal_fingerprint": GOLDEN_B_PERSONAL}) != plain["entry_hash"]
    base = entry(
        1,
        fingerprint=GOLDEN_B,
        personal_fingerprint=GOLDEN_B_PERSONAL,
        fingerprint_saves=[SAVE_1],
        personal_subjects=[ALICE],
    )
    assert base["entry_hash"] != entry(1)["entry_hash"]
    changes: tuple[dict[str, Any], ...] = (
        {"fingerprint": "fp1:" + "0" * 64},
        {"personal_fingerprint": "fp1:" + "0" * 64},
        {"personal_fingerprint": None},
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
