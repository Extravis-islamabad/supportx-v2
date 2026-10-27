"""Brand images with Pillow (WP-017): the variants every surface shows, made from the uploads.

Inputs are files that already passed the files service (scanned, metadata stripped). They are
decoded again here under the same limits as thumbnails (D-082 D4): a size cap before decoding,
the header's pixel count checked before any pixel is read, Pillow's bomb check made an error, and
only the first frame used. SVG is never accepted (it can carry scripts, D-090); every output is a
fresh PNG or ICO with no metadata.

Variants (names are the public asset names):

- `logo.png`: the light-mode logo, at most 960 x 240 (shown at 40 px high, x3 for sharp screens);
- `logo-dark.png`: the dark-mode logo when uploaded; otherwise, for a logo with transparency, the
  light one with near-black neutral pixels turned white (what `make brand-assets` does for
  SupportX's own logo); an opaque logo is shown as it is in dark mode;
- `logo-high-contrast.png`: all black, keeping transparency (only for logos with transparency);
- `icon.png`, `icon-high-contrast.png`: the square mark, 96 px;
- `favicon.ico` (16, 32, 48), `apple-touch-icon.png` (180, on white), `icon-192.png`,
  `icon-512.png`: from the icon, or from the logo fitted into a square when there is no icon.
"""

from __future__ import annotations

import asyncio
import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_INPUT_BYTES = 5 << 20
MAX_PIXELS = 25_000_000
MIN_SIDE = 16
LOGO_BOX = (960, 240)
ICON_SIDE = 96
NEUTRAL_SPREAD = 40
DARK_NEUTRAL = 110  # channels at or below this count as "black text" to recolour for dark mode
_FORMATS = ["PNG", "JPEG", "WEBP", "ICO"]


TOO_LARGE = "brand_image_too_large"
TOO_SMALL = "brand_image_too_small"
UNREADABLE = "brand_image_unreadable"


class BrandImageError(ValueError):
    """The image cannot be used (code for a translated message)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Variant:
    """One generated asset."""

    name: str
    content_type: str
    content: bytes


def _check_size(size: tuple[int, int]) -> None:
    width, height = size
    if width * height > MAX_PIXELS:
        raise BrandImageError(TOO_LARGE)
    if min(width, height) < MIN_SIDE:
        raise BrandImageError(TOO_SMALL)


def _decode(data: bytes) -> Image.Image:
    if len(data) > MAX_INPUT_BYTES:
        raise BrandImageError(TOO_LARGE)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            with Image.open(io.BytesIO(data), formats=_FORMATS) as image:
                _check_size(image.size)
                image.seek(0)
                frame = ImageOps.exif_transpose(image).convert("RGBA")
                frame.load()
                return frame
        except BrandImageError:
            raise
        except (
            UnidentifiedImageError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            OSError,
            ValueError,
            SyntaxError,  # raised by some Pillow plugins for malformed headers
        ):
            raise BrandImageError(UNREADABLE) from None


def _trim(image: Image.Image) -> Image.Image:
    box = image.getchannel("A").getbbox()
    return image.crop(box) if box else image


def has_transparency(image: Image.Image) -> bool:
    """Whether a meaningful share of the image is see-through (a cut-out logo)."""
    alpha = image.getchannel("A")
    histogram = alpha.histogram()
    see_through = sum(histogram[:250])
    return see_through > (image.width * image.height) // 50


def _fit(image: Image.Image, box: tuple[int, int]) -> Image.Image:
    copy = image.copy()
    copy.thumbnail(box, Image.Resampling.LANCZOS)
    return copy


def _square(
    image: Image.Image, side: int, margin: float, background: tuple[int, ...]
) -> Image.Image:
    inner = max(1, round(side * (1 - 2 * margin)))
    fitted = _fit(image, (inner, inner))
    tile = Image.new("RGBA", (side, side), background)
    tile.alpha_composite(fitted, ((side - fitted.width) // 2, (side - fitted.height) // 2))
    return tile


def _recolour_dark_text(image: Image.Image) -> Image.Image:
    """Near-black neutral pixels to white; colours (a gradient, a mark) stay."""
    out = image.copy()
    pixels = out.load()
    assert pixels is not None  # noqa: S101 - load() returns the access object for RGBA images
    for y in range(out.height):
        for x in range(out.width):
            r, g, b, a = pixels[x, y]  # type: ignore[misc]  # RGBA: always a 4-tuple
            if a and max(r, g, b) - min(r, g, b) <= NEUTRAL_SPREAD and max(r, g, b) <= DARK_NEUTRAL:
                pixels[x, y] = (255, 255, 255, a)
    return out


def _black(image: Image.Image) -> Image.Image:
    black = Image.new("RGBA", image.size, (0, 0, 0, 255))
    black.putalpha(image.getchannel("A"))
    return black


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()


def _ico(image: Image.Image) -> bytes:
    out = io.BytesIO()
    _square(image, 48, 0.03, (0, 0, 0, 0)).save(out, "ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    return out.getvalue()


def _render(logo: bytes, logo_dark: bytes | None, icon: bytes | None) -> list[Variant]:
    light = _fit(_trim(_decode(logo)), LOGO_BOX)
    transparent = has_transparency(light)
    variants = [Variant("logo.png", "image/png", _png(light))]
    if logo_dark is not None:
        dark = _fit(_trim(_decode(logo_dark)), LOGO_BOX)
        variants.append(Variant("logo-dark.png", "image/png", _png(dark)))
    elif transparent:
        variants.append(Variant("logo-dark.png", "image/png", _png(_recolour_dark_text(light))))
    if transparent:
        variants.append(Variant("logo-high-contrast.png", "image/png", _png(_black(light))))

    clear = (0, 0, 0, 0)
    if icon is not None:
        mark = _trim(_decode(icon))
        variants.append(Variant("icon.png", "image/png", _png(_square(mark, ICON_SIDE, 0, clear))))
        if has_transparency(mark):
            black = _square(_black(mark), ICON_SIDE, 0, clear)
            variants.append(Variant("icon-high-contrast.png", "image/png", _png(black)))
    else:
        mark = light
    variants += [
        Variant("favicon.ico", "image/x-icon", _ico(mark)),
        # iOS fills transparency with black: the touch icon gets a white tile and room round it.
        Variant("apple-touch-icon.png", "image/png", _png(_square(mark, 180, 0.12, (255,) * 4))),
        Variant("icon-192.png", "image/png", _png(_square(mark, 192, 0.08, clear))),
        Variant("icon-512.png", "image/png", _png(_square(mark, 512, 0.08, clear))),
    ]
    return variants


def check_image(data: bytes) -> None:
    """Raise BrandImageError when `data` cannot be used as a brand image."""
    _decode(data)


async def render(logo: bytes, logo_dark: bytes | None, icon: bytes | None) -> list[Variant]:
    """Every variant, made off the event loop under the pixel limit."""
    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        return await asyncio.to_thread(_render, logo, logo_dark, icon)
    finally:
        Image.MAX_IMAGE_PIXELS = previous
