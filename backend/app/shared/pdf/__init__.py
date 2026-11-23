"""PDF rendering with WeasyPrint, shared by report exports and asset labels (D-100 D8).

Moved here from analytics (WP-049b s3, agreed with lane C) so analytics and assets both use one
renderer and never each other. Callers build their own HTML; this package only renders it.

Only the worker image installs WeasyPrint (dependency group `pdf`). It is imported only inside
the functions that render, so this package loads anywhere (the API image, test discovery) and
`available()` says whether this process can render. Arabic and Urdu are shaped by Pango/HarfBuzz
and laid out right to left with the bundled Noto fonts.

D-100 D8 conditions, the same for every caller:
- The URL fetcher refuses everything except the bundled fonts: no network, no other file path.
  Callers escape every text and inline their images (SVG), and the fetcher makes that hold even
  if a template bug ever let a URL through.
- Fonts come from this package, so a PDF looks the same offline and air-gapped.
- Worker image only: nothing in a request renders a PDF.
"""

from functools import cache
from pathlib import Path
from typing import Any
from urllib.request import url2pathname

FONTS = (Path(__file__).resolve().parent / "fonts").resolve()
_FONT_FILES = {
    "sans": "NotoSans-Regular.ttf",
    "sans-bold": "NotoSans-Bold.ttf",
    "naskh": "NotoNaskhArabic-Regular.ttf",
    "naskh-bold": "NotoNaskhArabic-Bold.ttf",
}
# The font families the bundled faces declare: a caller's CSS names these.
SANS = "SupportX Sans"
NASKH = "SupportX Naskh"


class RefusedURL(ValueError):
    """A resource the PDF may not load."""


class PdfTooLarge(ValueError):
    """The PDF would pass the caller's page or byte cap (`limit` names which)."""

    def __init__(self, limit: str, found: int) -> None:
        """`limit`: "pages" or "bytes"; `found`: how many it had."""
        super().__init__(f"pdf over its {limit} cap ({found})")
        self.limit = limit
        self.found = found


def bundled_font(url: str) -> Path | None:
    """The bundled font a `file:` URL names, or None for anything else (D-100 D8)."""
    if not url.startswith("file:"):
        return None
    path = Path(url2pathname(url.split("?", maxsplit=1)[0].removeprefix("file:"))).resolve()
    return path if path.parent == FONTS and path.name in _FONT_FILES.values() else None


def available() -> bool:
    """Whether WeasyPrint and its Pango libraries load in this process (the worker image)."""
    try:
        import weasyprint  # noqa: F401, PLC0415 - probe only
    except (ImportError, OSError):
        return False
    return True


@cache
def _fetcher_class() -> type:
    from weasyprint.urls import URLFetcher, URLFetcherResponse  # noqa: PLC0415 - worker image only

    class ReportFetcher(URLFetcher):  # type: ignore[misc]  # untyped base class
        """Serves the bundled fonts; refuses every other URL (D-100 D8)."""

        def __init__(self) -> None:
            super().__init__(allowed_protocols=("file",), allow_redirects=False)
            self.refused: list[str] = []

        def fetch(self, url: str, headers: Any = None) -> Any:  # noqa: ANN401 - WeasyPrint's response type
            """A bundled font file, or RefusedURL."""
            del headers
            font = bundled_font(url)
            if font is not None:
                return URLFetcherResponse(
                    url, body=font.read_bytes(), headers={"Content-Type": "font/ttf"}
                )
            self.refused.append(url)
            msg = "resource refused"
            raise RefusedURL(msg)

    return ReportFetcher


def report_fetcher() -> Any:  # noqa: ANN401 - a WeasyPrint URLFetcher subclass instance
    """A fresh fetcher that records what it refused (`.refused`)."""
    return _fetcher_class()()


def font_faces() -> str:
    """The `@font-face` rules of the bundled fonts, for a caller's `<style>`."""
    faces = [
        (SANS, "sans", "normal"),
        (SANS, "sans-bold", "bold"),
        (NASKH, "naskh", "normal"),
        (NASKH, "naskh-bold", "bold"),
    ]
    return "\n".join(
        f'@font-face {{ font-family: "{family}"; font-weight: {weight}; '
        f'src: url("{(FONTS / _FONT_FILES[key]).as_uri()}"); }}'
        for family, key, weight in faces
    )


def render(
    html: str,
    fetcher: Any = None,  # noqa: ANN401 - see report_fetcher
    *,
    max_pages: int | None = None,
    max_bytes: int | None = None,
) -> bytes:
    """The PDF bytes of `html` (worker image only), within the caller's caps (PdfTooLarge)."""
    from weasyprint import HTML  # noqa: PLC0415 - worker image only

    document = HTML(
        string=html,
        base_url=FONTS.as_uri() + "/",
        url_fetcher=fetcher or report_fetcher(),
    ).render()
    if max_pages is not None and len(document.pages) > max_pages:
        limit = "pages"
        raise PdfTooLarge(limit, len(document.pages))
    pdf: bytes = document.write_pdf()
    if max_bytes is not None and len(pdf) > max_bytes:
        limit = "bytes"
        raise PdfTooLarge(limit, len(pdf))
    return pdf


__all__ = [
    "FONTS",
    "NASKH",
    "SANS",
    "PdfTooLarge",
    "RefusedURL",
    "available",
    "bundled_font",
    "font_faces",
    "render",
    "report_fetcher",
]
