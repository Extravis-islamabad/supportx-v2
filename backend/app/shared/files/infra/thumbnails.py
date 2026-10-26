"""Image thumbnails with Pillow, in the worker, under strict limits (D-081 D4).

A decompression bomb is a small file that decodes into a huge image. Defences, in order:

1. only files up to MAX_INPUT_BYTES are decoded at all;
2. the header is read first (`Image.open` is lazy) and images above MAX_PIXELS are refused before
   any pixel is decoded; Pillow's own bomb check is made an error at the same limit;
3. JPEGs are decoded at a reduced scale (`draft`), so a large photo never decodes at full size;
4. only the first frame of an animation is used.

The thumbnail is a fresh WebP, at most 320 px on its longest side, with no metadata at all.
Anything Pillow cannot read safely gives no thumbnail (the file still downloads).
"""

import asyncio
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

THUMB_SIDE = 320
MAX_PIXELS = 40_000_000  # e.g. 8000 x 5000
MAX_INPUT_BYTES = 50 << 20
_FORMATS = ["PNG", "JPEG", "GIF", "WEBP"]


def _make(data: bytes) -> bytes | None:
    if len(data) > MAX_INPUT_BYTES:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            with Image.open(io.BytesIO(data), formats=_FORMATS) as image:
                width, height = image.size
                if width * height > MAX_PIXELS or width < 1 or height < 1:
                    return None
                image.draft("RGB", (THUMB_SIDE * 2, THUMB_SIDE * 2))
                image.seek(0)
                frame = ImageOps.exif_transpose(image)
                frame = frame.convert("RGBA" if "A" in frame.getbands() else "RGB")
                frame.thumbnail((THUMB_SIDE, THUMB_SIDE))
                out = io.BytesIO()
                frame.save(out, "WEBP", quality=80, method=4)
                return out.getvalue()
        except (
            UnidentifiedImageError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            OSError,
            ValueError,
            SyntaxError,  # raised by some Pillow plugins for malformed headers
        ):
            return None


async def thumbnail(data: bytes) -> bytes | None:
    """A WebP thumbnail of an image, or None when it cannot be made safely (off the event loop)."""
    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        return await asyncio.to_thread(_make, data)
    finally:
        Image.MAX_IMAGE_PIXELS = previous
