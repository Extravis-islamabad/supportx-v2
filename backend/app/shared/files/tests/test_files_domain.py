"""Pure rules of the files service (WP-022): types, blocking, names, states, chunks, keys."""

import io
import struct
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image, PngImagePlugin

from app.shared.files.domain import chunks, metadata, tokens
from app.shared.files.domain.states import FileState, may_become, openable
from app.shared.files.domain.types import (
    DEFAULT_BLOCKED_EXTENSIONS,
    Family,
    Kind,
    blocked_reason,
    extension,
    inline_allowed,
    normalise_blocked,
    normalise_name,
    sniff,
)
from app.shared.files.keyring import KeyRing, KeyRingError

BLOCKED = list(DEFAULT_BLOCKED_EXTENSIONS)


@pytest.mark.parametrize(
    ("head", "content_type", "kind"),
    [
        (b"\x89PNG\r\n\x1a\n....", "image/png", Kind.IMAGE),
        (b"\xff\xd8\xff\xe0", "image/jpeg", Kind.IMAGE),
        (b"GIF89a....", "image/gif", Kind.IMAGE),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp", Kind.IMAGE),
        (b"%PDF-1.7\n", "application/pdf", Kind.PDF),
        (b"PK\x03\x04word/document.xml", "application/zip", Kind.OTHER),
        ("مرحبا hello\n".encode(), "text/plain", Kind.OTHER),
        (b"\x00\x01\x02binary", "application/octet-stream", Kind.OTHER),
    ],
)
def test_sniffs_the_real_type(head: bytes, content_type: str, kind: Kind) -> None:
    found = sniff(head)
    assert (found.content_type, found.kind, found.family) == (content_type, kind, None)


@pytest.mark.parametrize(
    ("head", "family"),
    [
        (b"MZ\x90\x00", Family.NATIVE),
        (b"\x7fELF\x02\x01", Family.NATIVE),
        (b"\xcf\xfa\xed\xfe", Family.NATIVE),
        (b"#!/bin/sh\nrm -rf /", Family.SCRIPT),
        (b"PK\x03\x04....META-INF/MANIFEST.MF", Family.JAVA),
    ],
)
def test_executables_are_blocked_whatever_their_name(head: bytes, family: Family) -> None:
    found = sniff(head)
    assert found.family == family
    assert blocked_reason("holiday-photo.jpg", found, BLOCKED) == "blocked_content"
    # An administrator who takes the family off the list accepts it (D-082: editable list).
    assert blocked_reason("tool.bin", found, [b for b in BLOCKED if b != family.value]) is None


def test_extension_list_blocks_and_is_normalised() -> None:
    text = sniff(b"echo hi")
    for name in ("run.BAT", "a.b.ps1", "x.js", "deploy.sh", "setup.msi", "app.jar", "evil.vbs"):
        assert blocked_reason(name, text, BLOCKED) == "blocked_extension", name
    assert blocked_reason("report.pdf", sniff(b"%PDF-1.4"), BLOCKED) is None
    assert normalise_blocked([".EXE", " sh ", "exe", "bad ext!", ""]) == ["exe", "sh"]
    assert extension("archive.tar.gz") == "gz"
    assert extension(".bashrc") == ""
    assert extension("noext") == ""


def test_markup_is_never_shown_inline() -> None:
    svg = sniff(b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>')
    html = sniff(b"<!DOCTYPE html><html><script>alert(1)</script>")
    assert (svg.content_type, svg.active_markup) == ("image/svg+xml", True)
    assert (html.content_type, html.active_markup) == ("text/html", True)
    assert not inline_allowed(svg)
    assert inline_allowed(sniff(b"%PDF-1.4"))
    assert inline_allowed(sniff(b"\x89PNG\r\n\x1a\n"))


def test_a_utf8_character_cut_by_the_sniff_window_is_still_text() -> None:
    assert sniff("ملف".encode()[:-1]).content_type == "text/plain"


def test_names_are_made_safe_and_arabic_is_kept() -> None:
    assert normalise_name("../../etc/passwd") == "passwd"
    assert normalise_name("C:\\Users\\a\\تقرير الربع.pdf") == "تقرير الربع.pdf"
    assert normalise_name('a"b<c>\x00\r\n.txt') == "abc.txt"
    assert normalise_name("...") == "file"
    long = "ب" * 300 + ".docx"
    cut = normalise_name(long)
    assert len(cut.encode()) <= 255
    assert cut.endswith(".docx")


def test_states() -> None:
    assert openable(FileState.CLEAN, scan_required=True)
    assert not openable(FileState.SCANNING, scan_required=False)
    assert not openable(FileState.NOT_SCANNED, scan_required=True)
    assert openable(FileState.NOT_SCANNED, scan_required=False)
    assert may_become(FileState.SCANNING, FileState.INFECTED)
    assert not may_become(FileState.INFECTED, FileState.CLEAN)  # blocked for good
    assert not may_become(FileState.DELETED, FileState.SCANNING)
    assert may_become(FileState.SCAN_FAILED, FileState.SCANNING)  # admin rescan
    assert not may_become(FileState.CLEAN, FileState.SCANNING)


def _encrypt(data: bytes, key: bytes, file_id: uuid.UUID) -> bytes:
    enc = chunks.Encryptor(key, file_id, uuid.uuid4())
    parts = [data[i : i + chunks.CHUNK] for i in range(0, len(data), chunks.CHUNK)] or [b""]
    body = b"".join(enc.seal(p, last=i == len(parts) - 1) for i, p in enumerate(parts))
    return enc.header.to_bytes() + body


def _read(stored: bytes, key: bytes, file_id: uuid.UUID, size: int, start: int, end: int) -> bytes:
    found = chunks.span(size, start, end)
    dec = chunks.Decryptor(key, file_id, chunks.Header.parse(stored[: chunks.HEADER]))
    out, pos = b"", found.stored_start
    lengths = chunks.chunk_lengths(size, found.first, found.last)
    for index, length in zip(range(found.first, found.last + 1), lengths, strict=True):
        last = index == chunks.chunk_count(size) - 1
        out += dec.open(index, stored[pos : pos + length], last=last)
        pos += length
    return out[found.skip : found.skip + found.length]


@pytest.mark.parametrize("size", [0, 1, chunks.CHUNK - 1, chunks.CHUNK, 2 * chunks.CHUNK + 7])
def test_chunked_encryption_round_trips_and_reads_ranges(size: int) -> None:
    key, file_id = b"k" * 32, uuid.uuid4()
    data = bytes(i % 251 for i in range(size))
    stored = _encrypt(data, key, file_id)
    assert len(stored) == chunks.encrypted_size(size)
    if size == 0:
        return
    assert _read(stored, key, file_id, size, 0, size - 1) == data
    start, end = size // 3, max(size // 3, size - 2)
    assert _read(stored, key, file_id, size, start, end) == data[start : end + 1]


def test_tampering_another_file_and_truncation_are_detected() -> None:
    key, file_id = b"k" * 32, uuid.uuid4()
    data = b"x" * (chunks.CHUNK + 10)
    stored = bytearray(_encrypt(data, key, file_id))
    stored[chunks.HEADER + 5] ^= 1
    with pytest.raises(chunks.ChunkError):
        _read(bytes(stored), key, file_id, len(data), 0, 10)
    good = _encrypt(data, key, file_id)
    with pytest.raises(chunks.ChunkError):  # the same bytes claimed by another file
        _read(good, key, uuid.uuid4(), len(data), 0, 10)
    # Cut after the first chunk and claim it is the whole file: the last-chunk flag differs.
    truncated = good[: chunks.HEADER + chunks.CHUNK + chunks.TAG]
    with pytest.raises(chunks.ChunkError):
        _read(truncated, key, file_id, chunks.CHUNK, 0, 10)
    with pytest.raises(chunks.ChunkError):
        chunks.Header.parse(b"nope")
    with pytest.raises(chunks.ChunkError):
        chunks.span(10, 5, 10)
    with pytest.raises(chunks.ChunkError):
        chunks.Encryptor(key, file_id, uuid.uuid4()).seal(b"short", last=False)


def test_link_tokens() -> None:
    key, now = b"s" * 32, datetime(2026, 10, 26, 12, tzinfo=UTC)
    grant = tokens.LinkGrant(
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        tokens.Disposition.INLINE,
        now + timedelta(minutes=5),
    )
    token = tokens.sign(grant, key)
    assert tokens.verify(token, key, now) == grant
    with pytest.raises(tokens.TokenError) as expired:
        tokens.verify(token, key, now + timedelta(minutes=5))
    assert expired.value.expired
    payload, signature = token.split(".")
    for forged in (f"{payload}.{signature[:-2]}AA", "junk", f"{payload[:-4]}AAAA.{signature}"):
        with pytest.raises(tokens.TokenError) as error:
            tokens.verify(forged, key, now)
        assert not error.value.expired
    with pytest.raises(tokens.TokenError):
        tokens.verify(token, b"other" * 8, now)


def test_key_ring_wraps_per_tenant_and_rotates() -> None:
    old = KeyRing.parse(KeyRing.generate("k1"))
    tenant, other = uuid.uuid4(), uuid.uuid4()
    key_id, wrapped = old.wrap(tenant, b"d" * 32)
    assert key_id == "k1"
    assert old.unwrap(tenant, key_id, wrapped) == b"d" * 32
    with pytest.raises(KeyRingError):
        old.unwrap(other, key_id, wrapped)  # bound to its tenant
    rotated = KeyRing.parse(
        f"{KeyRing.generate('k2')}, {KeyRing.generate('k1').split(':')[0]}:"
        f"{__import__('base64').b64encode(old.keys['k1']).decode()}"
    )
    assert rotated.active_id == "k2"
    assert rotated.needs_rewrap("k1")
    assert rotated.unwrap(tenant, "k1", wrapped) == b"d" * 32  # old files stay readable
    without_old = KeyRing.parse(KeyRing.generate("k2"))
    with pytest.raises(KeyRingError, match="not in the key ring"):
        without_old.unwrap(tenant, "k1", wrapped)
    assert old.link_key() != rotated.link_key()
    for bad in (
        "",
        "k1:notbase64!",
        "k1:" + "QUJD",
        "bad id:" + KeyRing.generate().split(":")[1],
        f"{KeyRing.generate('a')},{KeyRing.generate('a')}",
    ):
        with pytest.raises(KeyRingError):
            KeyRing.parse(bad)


def _jpeg_with_exif(orientation: int) -> bytes:
    image = Image.new("RGB", (4, 2), "red")
    exif = Image.Exif()
    exif[0x0112] = orientation
    exif[0x8825] = {2: (51.0, 30.0, 0.0)}  # GPSInfo: latitude
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif, comment=b"camera serial 1234")
    return out.getvalue()


def test_jpeg_metadata_is_stripped_but_orientation_kept() -> None:
    original = _jpeg_with_exif(6)
    result = metadata.strip("image/jpeg", original)
    assert result.stripped
    assert b"camera serial" not in result.data
    with Image.open(io.BytesIO(result.data)) as cleaned:
        exif = cleaned.getexif()
        assert exif.get(0x0112) == 6
        assert 0x8825 not in exif
        assert cleaned.size == (4, 2)
    upright = metadata.strip("image/jpeg", _jpeg_with_exif(1))
    with Image.open(io.BytesIO(upright.data)) as cleaned:
        assert 0x0112 not in cleaned.getexif()


def test_png_and_webp_metadata_is_stripped() -> None:
    info = PngImagePlugin.PngInfo()
    info.add_text("GPS", "51.5,-0.1")
    out = io.BytesIO()
    Image.new("RGB", (3, 3), "blue").save(out, "PNG", pnginfo=info)
    png = metadata.strip("image/png", out.getvalue())
    assert png.stripped
    assert b"51.5" not in png.data
    with Image.open(io.BytesIO(png.data)) as cleaned:
        assert cleaned.size == (3, 3)

    exif = Image.Exif()
    exif[0x8825] = {2: (51.0, 30.0, 0.0)}
    out = io.BytesIO()
    Image.new("RGB", (5, 5), "green").save(out, "WEBP", exif=exif)
    webp = metadata.strip("image/webp", out.getvalue())
    assert webp.stripped
    assert b"EXIF" not in webp.data[12:]
    with Image.open(io.BytesIO(webp.data)) as cleaned:
        assert cleaned.size == (5, 5)
        assert not cleaned.getexif()
    (riff_size,) = struct.unpack("<I", webp.data[4:8])
    assert riff_size == len(webp.data) - 8


def test_unknown_or_malformed_images_are_returned_unchanged() -> None:
    assert metadata.strip("image/gif", b"GIF89a...") == metadata.Stripped(
        b"GIF89a...", stripped=False
    )
    assert not metadata.strip("image/jpeg", b"\xff\xd8\xff\xe1\x00").stripped
    assert not metadata.strip("image/png", b"\x89PNG\r\n\x1a\n\x00\x00\x10\x00IHDR").stripped
    assert not metadata.strip(
        "image/webp", b"RIFF\x00\x00\x00\x00WEBPEXIF\xff\xff\x00\x00"
    ).stripped
    assert not metadata.strip("image/jpeg", b"not a jpeg").stripped
