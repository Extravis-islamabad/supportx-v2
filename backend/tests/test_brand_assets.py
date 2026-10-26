"""The brand asset generator (tooling/brand_assets.py, docs/architecture/branding.md)."""

import json
import struct
import zlib
from pathlib import Path

import pytest

from tooling import brand_assets as brand
from tooling.brand_assets import Image


def _logo() -> Image:
    """A tiny stand-in for the logo: a blue-to-purple square, a gap, then a black letter."""
    image = Image.blank(40, 10)
    for x in range(10):
        for y in range(10):
            mixed = (100 - x * 5, 100 - x * 7, 236 - x * 7, 255)
            image.pixels[(y * 40 + x) * 4 : (y * 40 + x) * 4 + 4] = bytes(mixed)
    for x in range(32, 38):
        for y in range(2, 9):
            image.pixels[(y * 40 + x) * 4 : (y * 40 + x) * 4 + 4] = bytes((0, 0, 0, 255))
    return image


def _palette_png(width: int, height: int, indices: bytes) -> bytes:
    """A palette PNG with transparency, as the real logo is (rows unfiltered)."""
    palette = bytes((0, 0, 0, 255, 0, 0, 102, 102, 236))
    alpha = bytes((0, 128, 255))
    rows = b"".join(b"\x00" + indices[y * width : (y + 1) * width] for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0)
    return (
        brand.PNG_SIGNATURE
        + brand.png_chunk(b"IHDR", header)
        + brand.png_chunk(b"PLTE", palette)
        + brand.png_chunk(b"tRNS", alpha)
        + brand.png_chunk(b"IDAT", zlib.compress(rows))
        + brand.png_chunk(b"IEND", b"")
    )


def test_png_round_trip_and_palette_decoding() -> None:
    image = _logo()
    assert brand.decode_png(brand.encode_png(image)) == image
    decoded = brand.decode_png(_palette_png(3, 1, bytes((0, 1, 2))))
    assert [decoded.get(x, 0) for x in range(3)] == [
        (0, 0, 0, 0),
        (255, 0, 0, 128),
        (102, 102, 236, 255),
    ]


def _filter(kind: int, line: bytes, previous: bytes, bpp: int) -> bytes:
    """The PNG encoder's side of each filter (spec section 9), to test the decoder against."""
    out = bytearray()
    for i, value in enumerate(line):
        left = line[i - bpp] if i >= bpp else 0
        up = previous[i]
        up_left = previous[i - bpp] if i >= bpp else 0
        predictor = {
            1: left,
            2: up,
            3: (left + up) >> 1,
            4: brand.paeth(left, up, up_left),
        }[kind]
        out.append((value - predictor) & 0xFF)
    return bytes(out)


@pytest.mark.parametrize("kind", [1, 2, 3, 4])
def test_every_png_filter_is_undone(kind: int) -> None:
    rows = [bytes((10, 200, 30, 255, 90, 15, 240, 128)), bytes((250, 5, 60, 0, 7, 99, 180, 64))]
    raw = b""
    previous = bytes(8)
    for row in rows:
        raw += bytes([kind]) + _filter(kind, row, previous, 4)
        previous = row
    assert brand.unfilter(raw, 2, 2, 4) == bytearray(b"".join(rows))


def test_rejects_what_it_cannot_decode() -> None:
    with pytest.raises(ValueError, match="not a PNG"):
        brand.decode_png(b"GIF89a")
    header = struct.pack(">IIBBBBB", 1, 1, 16, 6, 0, 0, 0)
    sixteen_bit = brand.PNG_SIGNATURE + brand.png_chunk(b"IHDR", header)
    sixteen_bit += brand.png_chunk(b"IDAT", zlib.compress(b"\x00" + bytes(8)))
    with pytest.raises(ValueError, match="only 8-bit"):
        brand.decode_png(sixteen_bit)
    with pytest.raises(ValueError, match="unknown PNG filter"):
        brand.unfilter_line(9, bytearray(4), bytearray(4), 4)


def test_rgb_pngs_decode_as_opaque() -> None:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    data = brand.PNG_SIGNATURE + brand.png_chunk(b"IHDR", header)
    data += brand.png_chunk(b"IDAT", zlib.compress(b"\x00\x10\x20\x30"))
    assert brand.decode_png(data).get(0, 0) == (16, 32, 48, 255)


def test_build_splits_icon_from_wordmark_and_recolours() -> None:
    assets = brand.build(_logo())
    assert (assets.icon.width, assets.icon.height) == (10, 10)
    # The black letter turns white in the dark-theme logo; the coloured icon is untouched.
    assert assets.logo_white_text.get(33, 3) == (255, 255, 255, 255)
    assert assets.logo_white_text.get(0, 0) == assets.logo_dark_text.get(0, 0)
    assert assets.logo_black.get(0, 0) == (0, 0, 0, 255)
    start, end = assets.gradient
    assert start[2] > end[2]  # the stand-in fades from blue


def test_build_needs_a_gap_between_icon_and_wordmark() -> None:
    with pytest.raises(ValueError, match="gap"):
        brand.build(Image.blank(5, 5, (90, 30, 200, 255)))


def test_resize_keeps_colour_at_transparent_edges() -> None:
    image = Image.blank(4, 4)
    image.pixels[0:4] = bytes((200, 0, 0, 255))
    small = brand.resize(image, 2, 2)
    r, g, b, a = small.get(0, 0)
    # Premultiplied averaging: a quarter coverage, still pure red (no dark fringe).
    assert (r, g, b) == (200, 0, 0)
    assert a == 64


def test_fit_square_ico_and_preview() -> None:
    icon = brand.build(_logo()).icon
    square = brand.fit_square(icon, 16, 0.1, (255, 255, 255, 255))
    assert (square.width, square.height) == (16, 16)
    assert square.get(0, 0) == (255, 255, 255, 255)
    ico = brand.encode_ico([square, brand.fit_square(icon, 256, 0, (0, 0, 0, 0))])
    reserved, kind, count = struct.unpack("<HHH", ico[:6])
    assert (reserved, kind, count) == (0, 1, 2)
    assert ico[6] == 16
    assert ico[22] == 0  # 0 means 256 px
    sheet = brand.preview([square], height=8, pad=2)
    assert sheet.get(0, 0)[:3] == brand.WHITE
    assert sheet.get(0, sheet.height - 1)[:3] == brand.DARK_BG


def test_contrast_matches_wcag() -> None:
    assert brand.contrast((0, 0, 0), brand.WHITE) == pytest.approx(21)
    assert brand.contrast(brand.WHITE, brand.WHITE) == pytest.approx(1)
    assert brand.mix("#7e40d1", 0.5, 255) == "#bea0e8"  # same as theme.ts lighten


def test_the_supportx_palette_meets_aa_and_matches_the_logo() -> None:
    palette = brand.Palette.load(brand.PALETTE)
    checks = palette.checks()
    assert all(ratio >= need for _, ratio, need in checks), checks
    logo = brand.build(brand.decode_png(brand.SOURCE.read_bytes()))
    sampled = tuple(brand.hex_colour(colour) for colour in logo.gradient)
    assert sampled == palette.sampled


def test_check_reports_stale_files_and_weak_colours(tmp_path: Path) -> None:
    assert brand.check()  # the committed files are current
    weak = {
        "sampled": {"start": "#000000", "end": "#000000"},
        "primary": "#bbbbff",
        "gradient": {"start": "#bbbbff", "end": "#ccccff"},
    }
    path = tmp_path / "palette.json"
    path.write_text(json.dumps(weak), encoding="utf-8")
    assert not brand.check(path)


def test_generate_writes_every_asset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "logo.png"
    source.write_bytes(brand.encode_png(_logo()))
    monkeypatch.setattr(brand, "REPO", tmp_path)
    for name in ("UI_ASSETS", "UI_PUBLIC", "KEYCLOAK_THEME", "DOCS"):
        monkeypatch.setattr(brand, name, tmp_path / name.lower())
    assets, palette = brand.generate(source, brand.PALETTE)
    written = sorted(path.name for path in tmp_path.rglob("*") if path.is_file())
    assert "favicon.ico" in written
    assert "supportx.css" in written
    assert "logo-high-contrast.png" in written
    manifest = json.loads((tmp_path / "ui_public/site.webmanifest").read_text(encoding="utf-8"))
    assert manifest["theme_color"] == palette.primary
    # The stand-in is not the real logo, so its sample differs from palette.json: reported.
    assert not brand.report(assets, palette)
