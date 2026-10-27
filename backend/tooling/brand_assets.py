"""Generate the SupportX brand assets from the one logo file (see docs/architecture/branding.md).

Source: ``docs/brand/supportx-logo-dark-text.png`` (gradient headset icon, black "SUPPORT",
gradient X, transparent background). From it this script writes:

- ``frontend/packages/ui/src/brand/assets/``: the logo with dark text (light theme), with white
  text (dark theme) and all black (high contrast), and the icon alone in colour and in black, at
  the sizes the UI shows them (x3 for sharp rendering on high-density screens);
- ``frontend/packages/ui/src/brand/public/``: ``favicon.ico`` (16, 32, 48), the 180 px Apple
  touch icon, the 192 and 512 px app icons and ``site.webmanifest`` (both apps serve this folder);
- ``deploy/helm/supportx/files/keycloak/themes/supportx/login/resources/``: logos, favicon and
  colours (CSS) for the Keycloak login page;
- ``docs/brand/``: full-size white-text logo and icon, and ``preview.png``, every asset on white
  and on #141414 (Ant Design's dark background) for a visual check;

Colours come from ``frontend/packages/ui/src/brand/palette.json``. The script prints the
gradient ends sampled from the icon and the WCAG contrast of every text/background pair the
palette makes, and exits 1 when one is below AA (AAA for high contrast) or the palette's
recorded sample no longer matches the logo.

Standard library only (zlib + struct): no image library is on the approved dependency list, and
the logo needs only decoding, area-average scaling, recolouring and PNG/ICO encoding.

Run: ``make brand-assets`` (``uv run python -m tooling.brand_assets``). Outputs are committed;
rerun after replacing the source logo.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

from app.modules.organization.domain.branding import (
    DARK_BG,
    WHITE,
    CheckCode,
    Colours,
    hex_colour,
)
from app.modules.organization.domain.login_css import LoginLogos, login_css

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Text pixels are near-neutral (black with anti-aliasing alpha); gradient pixels are saturated.
NEUTRAL_SPREAD = 40
# A run of fully transparent columns at least this wide separates the icon from the wordmark.
ICON_GAP = 20

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "docs/brand/supportx-logo-dark-text.png"
UI_ASSETS = REPO / "frontend/packages/ui/src/brand/assets"
UI_PUBLIC = REPO / "frontend/packages/ui/src/brand/public"
PALETTE = REPO / "frontend/packages/ui/src/brand/palette.json"
KEYCLOAK_THEME = REPO / "deploy/helm/supportx/files/keycloak/themes/supportx/login"
DOCS = REPO / "docs/brand"
DEFAULT_PALETTE_MODULE = REPO / "backend/app/modules/organization/domain/default_palette.py"

# Heights the UI renders (CSS px) times 3 for high-density screens.
LOGO_HEIGHT = 40 * 3
ICON_SIZE = 32 * 3


@dataclass
class Image:
    """8-bit RGBA pixels, row by row."""

    width: int
    height: int
    pixels: bytearray

    @classmethod
    def blank(
        cls, width: int, height: int, rgba: tuple[int, int, int, int] = (0, 0, 0, 0)
    ) -> Image:
        """A `width` x `height` image filled with `rgba`."""
        return cls(width, height, bytearray(bytes(rgba) * (width * height)))

    def get(self, x: int, y: int) -> tuple[int, int, int, int]:
        """The (r, g, b, a) of one pixel."""
        i = (y * self.width + x) * 4
        r, g, b, a = self.pixels[i : i + 4]
        return r, g, b, a

    def crop(self, left: int, top: int, right: int, bottom: int) -> Image:
        """Pixels in [left, right) x [top, bottom)."""
        out = bytearray()
        for y in range(top, bottom):
            start = (y * self.width + left) * 4
            out += self.pixels[start : start + (right - left) * 4]
        return Image(right - left, bottom - top, out)

    def paste(self, other: Image, left: int, top: int) -> None:
        """Copy `other` in at (left, top), replacing what is there."""
        for y in range(other.height):
            src = y * other.width * 4
            dst = ((top + y) * self.width + left) * 4
            self.pixels[dst : dst + other.width * 4] = other.pixels[src : src + other.width * 4]


# --- PNG ---------------------------------------------------------------------------------------


def paeth(a: int, b: int, c: int) -> int:
    """PNG's Paeth predictor (left, up, up-left)."""
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def unfilter_line(kind: int, line: bytearray, previous: bytearray, bpp: int) -> None:
    """Undo one row's PNG filter in place (filters 0 to 4)."""
    stride = len(line)
    if kind == 1:
        for i in range(bpp, stride):
            line[i] = (line[i] + line[i - bpp]) & 0xFF
    elif kind == 2:  # noqa: PLR2004 - PNG filter numbers
        for i in range(stride):
            line[i] = (line[i] + previous[i]) & 0xFF
    elif kind == 3:  # noqa: PLR2004
        for i in range(stride):
            left = line[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
    elif kind == 4:  # noqa: PLR2004
        for i in range(stride):
            left = line[i - bpp] if i >= bpp else 0
            up_left = previous[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + paeth(left, previous[i], up_left)) & 0xFF
    elif kind != 0:
        msg = f"unknown PNG filter {kind}"
        raise ValueError(msg)


def unfilter(raw: bytes, width: int, height: int, bpp: int) -> bytearray:
    """Decompressed IDAT rows (each led by its filter byte) to plain pixel bytes."""
    stride = width * bpp
    out = bytearray(stride * height)
    previous = bytearray(stride)
    pos = 0
    for y in range(height):
        line = bytearray(raw[pos + 1 : pos + 1 + stride])
        unfilter_line(raw[pos], line, previous, bpp)
        pos += 1 + stride
        out[y * stride : (y + 1) * stride] = line
        previous = line
    return out


def _chunks(data: bytes) -> dict[bytes, bytes]:
    """The PNG's chunks by type (IDAT parts joined in order)."""
    pos = len(PNG_SIGNATURE)
    found: dict[bytes, bytes] = {}
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        found[kind] = found.get(kind, b"") + data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IEND":
            break
    return found


def decode_png(data: bytes) -> Image:
    """Decode an 8-bit, non-interlaced RGB, RGBA or palette PNG (with tRNS) to RGBA."""
    if not data.startswith(PNG_SIGNATURE):
        msg = "not a PNG file"
        raise ValueError(msg)
    chunks = _chunks(data)
    header = struct.unpack(">IIBBBBB", chunks[b"IHDR"])
    palette, alpha, idat = chunks.get(b"PLTE", b""), chunks.get(b"tRNS", b""), chunks[b"IDAT"]
    width, height, depth, colour, _, _, interlace = header
    channels = {2: 3, 3: 1, 6: 4}.get(colour)
    if depth != 8 or interlace != 0 or channels is None:  # noqa: PLR2004
        msg = "only 8-bit, non-interlaced RGB, RGBA or palette PNGs are supported"
        raise ValueError(msg)
    raw = unfilter(zlib.decompress(idat), width, height, channels)
    if channels == 4:  # noqa: PLR2004
        return Image(width, height, raw)
    if channels == 3:  # noqa: PLR2004
        out = bytearray(width * height * 4)
        out[0::4], out[1::4], out[2::4] = raw[0::3], raw[1::3], raw[2::3]
        out[3::4] = b"\xff" * (width * height)
        return Image(width, height, out)
    lookup = [
        bytes(palette[i * 3 : i * 3 + 3]) + bytes([alpha[i] if i < len(alpha) else 255])
        for i in range(len(palette) // 3)
    ]
    return Image(width, height, bytearray(b"".join(lookup[index] for index in raw)))


def png_chunk(kind: bytes, body: bytes) -> bytes:
    """One PNG chunk: length, type, body, CRC."""
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def encode_png(image: Image) -> bytes:
    """RGBA PNG; each row uses the Sub filter (small files for flat logo artwork)."""
    stride = image.width * 4
    raw = bytearray()
    for y in range(image.height):
        line = image.pixels[y * stride : (y + 1) * stride]
        filtered = bytearray(line[:4])
        filtered += bytes((line[i] - line[i - 4]) & 0xFF for i in range(4, stride))
        raw += b"\x01" + filtered
    header = struct.pack(">IIBBBBB", image.width, image.height, 8, 6, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + png_chunk(b"IEND", b"")
    )


def encode_ico(images: list[Image]) -> bytes:
    """ICO file holding each image as an embedded PNG (every current browser reads these)."""
    blobs = [encode_png(image) for image in images]
    offset = 6 + 16 * len(images)
    directory = b""
    for image, blob in zip(images, blobs, strict=True):
        side = image.width if image.width < 256 else 0  # noqa: PLR2004 - 0 means 256 in ICO
        directory += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    return struct.pack("<HHH", 0, 1, len(images)) + directory + b"".join(blobs)


# --- Pixel operations --------------------------------------------------------------------------


def _resample_axis(src: list[float], count: int, size: int, new_size: int) -> list[float]:
    """Area-average `count` interleaved rows of `size` samples (4 channels) to `new_size`."""
    scale = size / new_size
    out = [0.0] * (count * new_size * 4)
    for n in range(new_size):
        start, end = n * scale, (n + 1) * scale
        weights: list[tuple[int, float]] = []
        i = int(start)
        while i < end and i < size:
            weights.append((i, min(end, i + 1) - max(start, i)))
            i += 1
        total = sum(w for _, w in weights)
        for row in range(count):
            base_src = row * size * 4
            base_dst = (row * new_size + n) * 4
            for c in range(4):
                out[base_dst + c] = sum(src[base_src + j * 4 + c] * w for j, w in weights) / total
    return out


def resize(image: Image, width: int, height: int) -> Image:
    """Area-average resize with premultiplied alpha (no dark fringes round transparent edges)."""
    pre: list[float] = []
    for i in range(0, len(image.pixels), 4):
        r, g, b, a = image.pixels[i : i + 4]
        k = a / 255
        pre += [r * k, g * k, b * k, float(a)]
    rows = _resample_axis(pre, image.height, image.width, width)
    # Transpose so the second pass also works along rows.
    cols = [0.0] * len(rows)
    for y in range(image.height):
        for x in range(width):
            cols[(x * image.height + y) * 4 : (x * image.height + y) * 4 + 4] = rows[
                (y * width + x) * 4 : (y * width + x) * 4 + 4
            ]
    done = _resample_axis(cols, width, image.height, height)
    out = bytearray(width * height * 4)
    for x in range(width):
        for y in range(height):
            src = (x * height + y) * 4
            pr, pg, pb, pa = done[src : src + 4]
            dst = (y * width + x) * 4
            scale = 255 / pa if pa > 0 else 0.0
            out[dst : dst + 4] = bytes(
                (
                    min(255, round(pr * scale)),
                    min(255, round(pg * scale)),
                    min(255, round(pb * scale)),
                    round(pa),
                )
            )
    return Image(width, height, out)


def scale_to_height(image: Image, height: int) -> Image:
    """`image` scaled to `height`, keeping its proportions."""
    return resize(image, max(1, round(image.width * height / image.height)), height)


def alpha_bounds(image: Image) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) of the non-transparent pixels, right/bottom exclusive."""
    xs = [x for x in range(image.width) if any(image.get(x, y)[3] for y in range(image.height))]
    ys = [y for y in range(image.height) if any(image.get(x, y)[3] for x in range(image.width))]
    return xs[0], ys[0], xs[-1] + 1, ys[-1] + 1


def trim(image: Image) -> Image:
    """`image` without its transparent border."""
    return image.crop(*alpha_bounds(image))


def column_runs(image: Image, gap: int = ICON_GAP) -> list[tuple[int, int]]:
    """Runs of columns with ink, split where at least `gap` empty columns come between."""
    inked = [any(image.get(x, y)[3] for y in range(image.height)) for x in range(image.width)]
    runs: list[tuple[int, int]] = []
    start: int | None = None
    empty = 0
    for x, has_ink in enumerate(inked):
        if has_ink:
            if start is None:
                start = x
            elif empty >= gap:
                runs.append((start, x - empty))
                start = x
            empty = 0
        elif start is not None:
            empty += 1
    if start is not None:
        runs.append((start, len(inked) - empty))
    return runs


def is_neutral(r: int, g: int, b: int) -> bool:
    """Grey, black or white (the wordmark), as opposed to the gradient."""
    return max(r, g, b) - min(r, g, b) < NEUTRAL_SPREAD


def recolour_neutral(image: Image, rgb: tuple[int, int, int]) -> Image:
    """The same artwork with every near-neutral pixel (the black text) set to `rgb`."""
    out = bytearray(image.pixels)
    for i in range(0, len(out), 4):
        if out[i + 3] and is_neutral(out[i], out[i + 1], out[i + 2]):
            out[i : i + 3] = bytes(rgb)
    return Image(image.width, image.height, out)


def monochrome(image: Image, rgb: tuple[int, int, int]) -> Image:
    """Every pixel set to `rgb`, alpha kept: the one-colour logo for high-contrast mode."""
    out = bytearray(image.pixels)
    for i in range(0, len(out), 4):
        out[i : i + 3] = bytes(rgb)
    return Image(image.width, image.height, out)


def fit_square(
    image: Image, size: int, margin: float, background: tuple[int, int, int, int]
) -> Image:
    """`image` scaled into a `size` square with `margin` (fraction of the side) on every edge."""
    inner = size - 2 * round(size * margin)
    factor = inner / max(image.width, image.height)
    scaled = resize(
        image, max(1, round(image.width * factor)), max(1, round(image.height * factor))
    )
    canvas = Image.blank(size, size, background)
    return composite(canvas, scaled, (size - scaled.width) // 2, (size - scaled.height) // 2)


def composite(base: Image, top: Image, left: int, top_y: int) -> Image:
    """`top` drawn over `base` at (left, top_y) with alpha blending ("over")."""
    out = Image(base.width, base.height, bytearray(base.pixels))
    for y in range(top.height):
        for x in range(top.width):
            r, g, b, a = top.get(x, y)
            if a == 0:
                continue
            i = ((top_y + y) * out.width + left + x) * 4
            br, bg, bb, ba = out.pixels[i : i + 4]
            fa = a / 255
            na = fa + ba / 255 * (1 - fa)
            mixed = [
                round((src * fa + dst * (ba / 255) * (1 - fa)) / na)
                for src, dst in ((r, br), (g, bg), (b, bb))
            ]
            out.pixels[i : i + 4] = bytes([*mixed, round(na * 255)])
    return out


# --- Colour ------------------------------------------------------------------------------------


def gradient_ends(
    icon: Image, share: float = 0.04
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Mean colour of the opaque, saturated pixels in the leftmost and rightmost `share` columns."""
    band = max(1, round(icon.width * share))

    def mean(columns: range) -> tuple[int, int, int]:
        picked = [
            icon.get(x, y)[:3]
            for x in columns
            for y in range(icon.height)
            if icon.get(x, y)[3] == 255 and not is_neutral(*icon.get(x, y)[:3])  # noqa: PLR2004
        ]
        if not picked:
            msg = "no opaque coloured pixels at the icon's edge"
            raise ValueError(msg)
        r, g, b = (round(sum(p[c] for p in picked) / len(picked)) for c in range(3))
        return r, g, b

    return mean(range(band)), mean(range(icon.width - band, icon.width))


# --- Assets ------------------------------------------------------------------------------------


@dataclass
class Assets:
    """Full-size artwork cut and recoloured from the source, and its sampled gradient."""

    logo_dark_text: Image
    logo_white_text: Image
    logo_black: Image
    icon: Image
    icon_black: Image
    gradient: tuple[tuple[int, int, int], tuple[int, int, int]]


def build(source: Image) -> Assets:
    """Split the source into the full logo, the icon and their recoloured versions."""
    logo = trim(source)
    runs = column_runs(logo)
    if len(runs) < 2:  # noqa: PLR2004
        msg = "could not find the gap between the icon and the wordmark"
        raise ValueError(msg)
    left, right = runs[0]
    icon = trim(logo.crop(left, 0, right, logo.height))
    black = (0, 0, 0)
    return Assets(
        logo_dark_text=logo,
        logo_white_text=recolour_neutral(logo, WHITE),
        logo_black=monochrome(logo, black),
        icon=icon,
        icon_black=monochrome(icon, black),
        gradient=gradient_ends(icon),
    )


def preview(images: list[Image], height: int = 64, pad: int = 16) -> Image:
    """Every image on a white row and on a #141414 row, scaled to `height`."""
    scaled = [scale_to_height(image, height) for image in images]
    width = sum(image.width for image in scaled) + pad * (len(scaled) + 1)
    sheet = Image.blank(width, 2 * (height + 2 * pad), (*WHITE, 255))
    dark_row = Image.blank(width, height + 2 * pad, (*DARK_BG, 255))
    sheet.paste(dark_row, 0, height + 2 * pad)
    for row in range(2):
        x = pad
        for image in scaled:
            sheet = composite(sheet, image, x, row * (height + 2 * pad) + pad)
            x += image.width + pad
    return sheet


@dataclass(frozen=True)
class Palette:
    """frontend/packages/ui/src/brand/palette.json, and the shades derived from it.

    The derivations live in the organization module's branding rules (shared with tenant
    branding, WP-017) and match ``frontend/packages/ui/src/theme.ts``.
    """

    sampled: tuple[str, str]
    primary: str
    gradient: tuple[str, str]

    @classmethod
    def load(cls, path: Path) -> Palette:
        """Read palette.json."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            sampled=(data["sampled"]["start"], data["sampled"]["end"]),
            primary=data["primary"],
            gradient=(data["gradient"]["start"], data["gradient"]["end"]),
        )

    @property
    def colours(self) -> Colours:
        """The chosen colours, with their derived shades."""
        return Colours(self.primary, self.gradient)

    @property
    def hover(self) -> str:
        """Buttons darken on hover and press, so white text stays above AA in every state."""
        return self.colours.hover

    @property
    def dark_text(self) -> str:
        """Links and selected text on dark backgrounds."""
        return self.colours.dark_text

    @property
    def high_contrast(self) -> str:
        """Primary for high contrast (AAA with white)."""
        return self.colours.high_contrast

    def checks(self) -> list[tuple[str, float, float]]:
        """(what, ratio, required) for every text/background pair the brand colours make."""
        return [(CHECK_TEXT[c.code], c.ratio, c.required) for c in self.colours.checks()]


CHECK_TEXT = {
    CheckCode.TEXT_ON_PRIMARY: "white text on primary (light, dark)",
    CheckCode.LINKS_ON_WHITE: "primary links on white",
    CheckCode.TEXT_ON_HOVER: "white text on hovered primary",
    CheckCode.DARK_LINKS: "dark-mode links on #141414",
    CheckCode.DARK_LINKS_RAISED: "dark-mode links on #1f1f1f",
    CheckCode.HIGH_CONTRAST: "high-contrast primary with white",
    CheckCode.TEXT_ON_GRADIENT: "white text anywhere on the gradient",
}


def default_palette_module(palette: Palette) -> str:
    """The backend's copy of the default colours (e-mails and unknown hosts need them too)."""
    return DEFAULT_PALETTE.format(
        primary=palette.primary, start=palette.gradient[0], end=palette.gradient[1]
    )


DEFAULT_PALETTE = '''"""SupportX default colours from palette.json (generated: make brand-assets).

The backend cannot read frontend/packages/ui/src/brand/palette.json at run time (it is not in
the API image), so `make brand-assets` writes this copy and `--check` keeps it in sync.
"""

PRIMARY = "{primary}"
GRADIENT_START = "{start}"
GRADIENT_END = "{end}"
'''


def keycloak_css(palette: Palette) -> str:
    """The login theme's stylesheet for `palette` (the logos sit next to it in the theme)."""
    return login_css(
        palette.colours,
        LoginLogos(
            "../img/logo-dark-text.png",
            "../img/logo-white-text.png",
            "../img/logo-high-contrast.png",
        ),
    )


def manifest(theme_colour: str) -> str:
    """site.webmanifest (the icons sit next to it)."""
    icons = [
        {"src": f"icon-{side}.png", "sizes": f"{side}x{side}", "type": "image/png"}
        for side in (192, 512)
    ]
    body = {
        "name": "SupportX",
        "short_name": "SupportX",
        "icons": icons,
        "theme_color": theme_colour,
        "background_color": "#ffffff",
        "display": "standalone",
    }
    return json.dumps(body, indent=2) + "\n"


def say(message: str) -> None:
    """One line on stdout (a dev tool's progress and results)."""
    sys.stdout.write(message + "\n")


def write(path: Path, data: bytes | str) -> None:
    """Write a generated file, creating its folder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    say(f"wrote {path.relative_to(REPO)}")


def generate(source_path: Path = SOURCE, palette_path: Path = PALETTE) -> tuple[Assets, Palette]:
    """Write every asset; returns what was measured, for `report`."""
    assets = build(decode_png(source_path.read_bytes()))
    palette = Palette.load(palette_path)
    transparent = (0, 0, 0, 0)
    ui = {
        "logo-dark-text.png": scale_to_height(assets.logo_dark_text, LOGO_HEIGHT),
        "logo-white-text.png": scale_to_height(assets.logo_white_text, LOGO_HEIGHT),
        "logo-high-contrast.png": scale_to_height(assets.logo_black, LOGO_HEIGHT),
        "icon.png": fit_square(assets.icon, ICON_SIZE, 0.0, transparent),
        "icon-high-contrast.png": fit_square(assets.icon_black, ICON_SIZE, 0.0, transparent),
    }
    for name, image in ui.items():
        write(UI_ASSETS / name, encode_png(image))

    # Tiny sizes keep a small margin so the headset's edge is not cut by the tab's rounding.
    favicons = [fit_square(assets.icon, side, 0.03, transparent) for side in (16, 32, 48)]
    ico = encode_ico(favicons)
    write(UI_PUBLIC / "favicon.ico", ico)
    # iOS fills transparency with black: the touch icon gets a white tile and room round it.
    touch = fit_square(assets.icon, 180, 0.12, (*WHITE, 255))
    write(UI_PUBLIC / "apple-touch-icon.png", encode_png(touch))
    app_icons = {side: fit_square(assets.icon, side, 0.08, transparent) for side in (192, 512)}
    for side, image in app_icons.items():
        write(UI_PUBLIC / f"icon-{side}.png", encode_png(image))
    write(UI_PUBLIC / "site.webmanifest", manifest(palette.primary))

    for name in ("logo-dark-text.png", "logo-white-text.png", "logo-high-contrast.png"):
        write(KEYCLOAK_THEME / "resources/img" / name, encode_png(ui[name]))
    write(KEYCLOAK_THEME / "resources/img/favicon.ico", ico)
    write(KEYCLOAK_THEME / "resources/css/supportx.css", keycloak_css(palette))
    write(DEFAULT_PALETTE_MODULE, default_palette_module(palette))

    write(DOCS / "supportx-logo-white-text.png", encode_png(assets.logo_white_text))
    write(DOCS / "supportx-icon.png", encode_png(fit_square(assets.icon, 512, 0.0, transparent)))
    sheet = preview([*ui.values(), *favicons, touch, *app_icons.values()])
    write(DOCS / "preview.png", encode_png(sheet))
    return assets, palette


def report(assets: Assets, palette: Palette) -> bool:
    """Print the sampled colours and every contrast check; False when one fails."""
    start, end = (hex_colour(colour) for colour in assets.gradient)
    say(f"gradient sampled from the icon: {start} -> {end}")
    ok = True
    if (start, end) != palette.sampled:
        say(f"  palette.json records {palette.sampled}: update it (the logo changed)")
        ok = False
    say(
        f"primary {palette.primary}, hover {palette.hover}, dark-mode text {palette.dark_text}, "
        f"high contrast {palette.high_contrast}, gradient {palette.gradient[0]} -> "
        f"{palette.gradient[1]}"
    )
    for what, ratio, need in palette.checks():
        verdict = "ok" if ratio >= need else "FAIL"
        ok = ok and ratio >= need
        say(f"  {what}: {ratio:.2f}:1 (needs {need}:1) {verdict}")
    return ok


def check(palette_path: Path = PALETTE) -> bool:
    """CI: the palette passes every contrast check and the files made from it are current.

    Only the text outputs are compared (fast); the images change only with the source logo.
    """
    palette = Palette.load(palette_path)
    ok = True
    for what, ratio, need in palette.checks():
        if ratio < need:
            say(f"brand palette: {what} is {ratio:.2f}:1, needs {need}:1")
            ok = False
    expected = {
        KEYCLOAK_THEME / "resources/css/supportx.css": keycloak_css(palette),
        UI_PUBLIC / "site.webmanifest": manifest(palette.primary),
        DEFAULT_PALETTE_MODULE: default_palette_module(palette),
    }
    for path, text in expected.items():
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if current != text:
            say(f"{path.relative_to(REPO)} is out of date: run make brand-assets")
            ok = False
    if ok:
        say("brand assets: up to date, palette meets WCAG AA")
    return ok


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI over tested functions
    """Generate the assets, or with --check only verify them."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--palette", type=Path, default=PALETTE)
    parser.add_argument("--check", action="store_true", help="verify only (CI)")
    args = parser.parse_args(argv)
    if args.check:
        return 0 if check(args.palette) else 1
    return 0 if report(*generate(args.source, args.palette)) else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
