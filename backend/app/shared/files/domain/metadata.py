"""Remove metadata from images without re-encoding them (D-082 D4: strip GPS/EXIF).

Phone photos carry EXIF with GPS coordinates, camera serials and timestamps; editors add XMP,
IPTC and text chunks. These are removed losslessly, by dropping the segments that hold them:

- JPEG: APP1 (EXIF, XMP), APP13 (Photoshop/IPTC) and comments go. The EXIF orientation is kept
  in a minimal new EXIF block (one tag), so photos are not shown sideways. Colour profiles
  (APP2) and the image data stay byte for byte.
- PNG: `eXIf`, `tEXt`, `zTXt`, `iTXt` and `tIME` chunks go.
- WebP: `EXIF` and `XMP ` chunks go and the extended header's flags are cleared.
- GIF has no EXIF; other types are returned unchanged.

Malformed input is returned unchanged (`stripped=False`): a file that cannot be parsed here is
still only offered as a download, never re-processed by a decoder.
"""

import struct
from dataclasses import dataclass

_JPEG_DROP = {0xE1, 0xED, 0xFE}  # APP1, APP13, COM
_PNG_DROP = {b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"tIME"}
_WEBP_DROP = {b"EXIF", b"XMP "}
_ORIENTATION_TAG = 0x0112
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class _MalformedError(ValueError):
    """The image does not follow its format (it is then returned unchanged)."""


@dataclass(frozen=True)
class Stripped:
    """The cleaned bytes and whether anything was removed."""

    data: bytes
    stripped: bool


def strip(content_type: str, data: bytes) -> Stripped:
    """`data` without metadata, for the sniffed `content_type`."""
    try:
        if content_type == "image/jpeg":
            return _jpeg(data)
        if content_type == "image/png":
            return _png(data)
        if content_type == "image/webp":
            return _webp(data)
    except (IndexError, struct.error, ValueError):
        return Stripped(data, stripped=False)
    return Stripped(data, stripped=False)


def _exif_orientation(segment: bytes) -> int | None:
    """The orientation (1-8) from an APP1 EXIF payload, or None."""
    if not segment.startswith(b"Exif\x00\x00"):
        return None
    tiff = segment[6:]
    order = {b"II": "<", b"MM": ">"}.get(tiff[:2])
    if order is None:
        return None
    (ifd,) = struct.unpack(order + "I", tiff[4:8])
    (count,) = struct.unpack(order + "H", tiff[ifd : ifd + 2])
    for n in range(count):
        entry = tiff[ifd + 2 + 12 * n : ifd + 14 + 12 * n]
        tag, kind, _, value = struct.unpack(order + "HHI4s", entry)
        if tag == _ORIENTATION_TAG and kind == 3:  # noqa: PLR2004 - TIFF type SHORT
            (orientation,) = struct.unpack(order + "H", value[:2])
            return orientation if 1 <= orientation <= 8 else None  # noqa: PLR2004
    return None


def _orientation_segment(orientation: int) -> bytes:
    """A minimal APP1 EXIF segment holding only the orientation."""
    tiff = (
        b"MM\x00\x2a\x00\x00\x00\x08"  # big-endian TIFF, IFD0 at offset 8
        + struct.pack(">H", 1)
        + struct.pack(">HHIH2x", _ORIENTATION_TAG, 3, 1, orientation)
        + struct.pack(">I", 0)
    )
    payload = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


def _jpeg(data: bytes) -> Stripped:
    if not data.startswith(b"\xff\xd8"):
        return Stripped(data, stripped=False)
    out = bytearray(b"\xff\xd8")
    pos, removed, orientation = 2, False, None
    while pos < len(data):
        if data[pos] != 0xFF:  # noqa: PLR2004
            raise _MalformedError
        marker = data[pos + 1]
        if marker == 0xFF:  # noqa: PLR2004 - fill byte
            pos += 1
            continue
        if marker == 0xDA:  # noqa: PLR2004 - start of scan: the rest is image data
            if orientation is not None and orientation != 1:
                out += _orientation_segment(orientation)
            out += data[pos:]
            return Stripped(bytes(out), removed)
        if 0xD0 <= marker <= 0xD9 or marker == 0x01:  # noqa: PLR2004 - markers without length
            out += data[pos : pos + 2]
            pos += 2
            continue
        (length,) = struct.unpack(">H", data[pos + 2 : pos + 4])
        segment = data[pos : pos + 2 + length]
        if marker in _JPEG_DROP:
            removed = True
            if marker == 0xE1 and orientation is None:  # noqa: PLR2004
                orientation = _exif_orientation(segment[4:])
        else:
            out += segment
        pos += 2 + length
    raise _MalformedError


def _png(data: bytes) -> Stripped:
    if not data.startswith(_PNG_SIGNATURE):
        return Stripped(data, stripped=False)
    out = bytearray(_PNG_SIGNATURE)
    pos, removed = len(_PNG_SIGNATURE), False
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        end = pos + 12 + length
        if end > len(data):
            raise _MalformedError
        if kind in _PNG_DROP:
            removed = True
        else:
            out += data[pos:end]
        pos = end
        if kind == b"IEND":
            break
    return Stripped(bytes(out), removed)


def _webp(data: bytes) -> Stripped:
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return Stripped(data, stripped=False)
    chunks: list[bytes] = []
    pos, removed = 12, False
    while pos + 8 <= len(data):
        kind = data[pos : pos + 4]
        (length,) = struct.unpack("<I", data[pos + 4 : pos + 8])
        end = pos + 8 + length + (length & 1)
        if end > len(data):
            raise _MalformedError
        chunk = data[pos:end]
        pos = end
        if kind in _WEBP_DROP:
            removed = True
            continue
        if kind == b"VP8X":
            flags = chunk[8] & ~0x0C  # clear the EXIF (0x08) and XMP (0x04) bits
            chunk = chunk[:8] + bytes([flags]) + chunk[9:]
        chunks.append(chunk)
    body = b"WEBP" + b"".join(chunks)
    return Stripped(b"RIFF" + struct.pack("<I", len(body)) + body, removed)
