"""The sealed-blob codec and the key ring (ADR-048): pure, no I/O."""

import pytest

from app.core.config import SESSION_KEY_ID_PATTERN
from app.shared.crypto import (
    KeyMaterial,
    KeyRing,
    from_text,
    key_id_of,
    open_sealed,
    seal,
    to_text,
)
from app.shared.crypto.codec import KEY_ID_PATTERN, NONCE_BYTES, TAG_BYTES, KeyLookup

NEW = KeyMaterial("k2", b"n" * 40)
OLD = KeyMaterial("k1", b"o" * 40)


def lookup(*keys: KeyMaterial) -> KeyLookup:
    found = {key.id: key.secret for key in keys}
    return found.get


def test_a_round_trip_opens_what_was_sealed() -> None:
    blob = seal(NEW, "bff-session", ["sx:session:abc"], b"hello")
    assert open_sealed(lookup(NEW), "bff-session", ["sx:session:abc"], blob) == b"hello"
    assert b"hello" not in blob


def test_the_blob_layout_is_version_key_id_nonce_ciphertext() -> None:
    blob = seal(NEW, "bff-session", ["x"], b"abc")
    assert blob[0] == 0x02
    assert blob[1] == len("k2")
    assert blob[2:4] == b"k2"
    assert len(blob) == 4 + NONCE_BYTES + len(b"abc") + TAG_BYTES
    assert key_id_of(blob) == "k2"


def test_two_seals_of_the_same_value_differ() -> None:
    assert seal(NEW, "p", ["x"], b"v") != seal(NEW, "p", ["x"], b"v")


def test_a_wrong_purpose_does_not_open() -> None:
    blob = seal(NEW, "bff-session", ["x"], b"v")
    assert open_sealed(lookup(NEW), "field/webhook", ["x"], blob) is None


def test_a_wrong_bound_to_does_not_open() -> None:
    blob = seal(NEW, "p", ["record-1"], b"v")
    assert open_sealed(lookup(NEW), "p", ["record-2"], blob) is None
    assert open_sealed(lookup(NEW), "p", ["record-1", "more"], blob) is None


def test_bound_to_parts_never_run_together() -> None:
    blob = seal(NEW, "p", ["a", "bc"], b"v")
    assert open_sealed(lookup(NEW), "p", ["ab", "c"], blob) is None
    assert open_sealed(lookup(NEW), "p", ["a", "bc"], blob) == b"v"


@pytest.mark.parametrize("parts", [[""], ["a", ""], ["a\x00b"]])
def test_empty_parts_or_parts_with_nul_are_refused(parts: list[str]) -> None:
    with pytest.raises(ValueError, match="bound_to"):
        seal(NEW, "p", parts, b"v")
    with pytest.raises(ValueError, match="bound_to"):
        open_sealed(lookup(NEW), "p", parts, seal(NEW, "p", ["x"], b"v"))


def test_bound_to_needs_at_least_one_part() -> None:
    with pytest.raises(ValueError, match="at least one part"):
        seal(NEW, "p", [], b"v")
    with pytest.raises(ValueError, match="at least one part"):
        open_sealed(lookup(NEW), "p", (), seal(NEW, "p", ["x"], b"v"))


def test_a_single_string_is_not_taken_as_its_characters() -> None:
    with pytest.raises(TypeError):
        seal(NEW, "p", "abc", b"v")


def test_a_tampered_key_id_or_header_does_not_open() -> None:
    blob = seal(NEW, "p", ["x"], b"v")
    renamed = blob[:2] + b"k1" + blob[4:]  # same length, another listed key's ID
    assert open_sealed(lookup(NEW, KeyMaterial("k1", NEW.secret)), "p", ["x"], renamed) is None
    for header in (b"\x01", b"\x03"):
        assert open_sealed(lookup(NEW), "p", ["x"], header + blob[1:]) is None
    assert open_sealed(lookup(NEW), "p", ["x"], blob[:1] + b"\x03" + blob[2:]) is None
    flipped = bytearray(blob)
    flipped[-1] ^= 1
    assert open_sealed(lookup(NEW), "p", ["x"], bytes(flipped)) is None


def test_an_unknown_key_does_not_open() -> None:
    blob = seal(NEW, "p", ["x"], b"v")
    assert open_sealed(lookup(OLD), "p", ["x"], blob) is None
    # Same ID, other secret: a bad tag.
    assert open_sealed(lookup(KeyMaterial("k2", b"z" * 40)), "p", ["x"], blob) is None


@pytest.mark.parametrize("blob", [b"", b"\x02", b"\x02\x02k2", b"\x02\x02K2" + b"\x00" * 40])
def test_malformed_blobs_do_not_open(blob: bytes) -> None:
    assert open_sealed(lookup(NEW), "p", ["x"], blob) is None


@pytest.mark.parametrize("key_id", ["", "K1", "a" * 33, "key id", "ключ", "a.b"])
def test_bad_key_ids_are_refused(key_id: str) -> None:
    with pytest.raises(ValueError, match="key IDs"):
        KeyMaterial(key_id, b"s" * 40)


@pytest.mark.parametrize("purpose", ["", "Bff", "a b", "a" * 65, "a\x00"])
def test_bad_purposes_are_refused(purpose: str) -> None:
    with pytest.raises(ValueError, match="purposes"):
        seal(NEW, purpose, ["x"], b"v")


def test_a_key_needs_a_secret_and_never_shows_it() -> None:
    with pytest.raises(ValueError, match="secret"):
        KeyMaterial("k1", b"")
    assert "nnnn" not in repr(NEW)


def test_the_text_form_round_trips() -> None:
    blob = seal(NEW, "p", ["x"], b"value")
    text = to_text(blob)
    assert text.startswith("sx2:")
    assert "=" not in text
    assert "+" not in text
    assert "/" not in text
    assert from_text(text) == blob


@pytest.mark.parametrize("text", ["", "sx1:AAAA", "AAAA", "sx2:AA==", "sx2:A+/A", "sx2:A"])
def test_text_that_is_no_text_form_gives_none(text: str) -> None:
    assert from_text(text) is None


def test_config_and_codec_agree_on_key_ids() -> None:
    assert SESSION_KEY_ID_PATTERN.pattern == KEY_ID_PATTERN.pattern


# --- the ring ------------------------------------------------------------------------------------


def test_the_newest_key_seals_and_every_listed_key_opens() -> None:
    before = KeyRing.of([OLD])
    sealed_before = before.seal("p", ["x"], b"old")
    ring = KeyRing.of([NEW, OLD])
    sealed_now = ring.seal("p", ["x"], b"new")
    assert key_id_of(sealed_now) == "k2"
    assert ring.open("p", ["x"], sealed_before) == b"old"
    assert ring.open("p", ["x"], sealed_now) == b"new"
    assert ring.is_current(sealed_now)
    assert not ring.is_current(sealed_before)
    assert ring.ids == ("k2", "k1")


def test_a_removed_key_no_longer_opens() -> None:
    sealed = KeyRing.of([NEW, OLD]).seal("p", ["x"], b"v")
    old_only = KeyRing.of([OLD]).seal("p", ["x"], b"w")
    assert KeyRing.of([NEW]).open("p", ["x"], old_only) is None
    assert KeyRing.of([NEW]).open("p", ["x"], sealed) == b"v"


def test_a_ring_is_never_empty_and_never_lists_an_id_twice() -> None:
    with pytest.raises(ValueError, match="at least one"):
        KeyRing.of([])
    with pytest.raises(ValueError, match="unique"):
        KeyRing.of([NEW, KeyMaterial("k2", b"x" * 40)])


def test_keys_for_one_purpose_never_open_another() -> None:
    """HKDF per purpose: the same ring key gives each purpose its own AES key."""
    ring = KeyRing.of([NEW])
    blob = ring.seal("bff-session", ["x"], b"v")
    assert ring.open("bff-session", ["x"], blob) == b"v"
    assert ring.open("field/x", ["x"], blob) is None
