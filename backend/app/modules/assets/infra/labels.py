"""Label codes and the label PDF (REQ-AST-039; D-141): segno and python-barcode, as SVG.

Behind two small interfaces, so either library can be swapped without touching the service:
- `CodeRenderer` draws a QR code or a Code 128 barcode as inline SVG, offline (no network, no
  files). The default is segno (BSD) for QR and python-barcode (MIT) for Code 128.
- `render_labels` builds the labels' HTML (every text escaped, the codes inline) and renders it
  with the shared PDF renderer (app/shared/pdf: bundled fonts only, every other URL refused,
  worker image only), within the label caps: pages, labels per job and output bytes.

Arabic and Urdu names are laid out right to left (the page's direction follows the language)
and each name is isolated, so a Latin tag keeps its order beside Arabic text.
"""

import re
from collections.abc import Callable, Sequence
from html import escape
from typing import Any, Protocol

from app.modules.assets.domain.labels import (
    BYTES_MAX,
    LAYOUTS,
    PAGES_MAX,
    Label,
    LabelLayout,
    Symbology,
)
from app.shared import pdf
from app.shared.labels import RTL_LANGUAGES

_PROLOG = re.compile(r"^.*?(?=<svg\b)", re.DOTALL)
_ROOT = re.compile(r"<svg\b[^>]*>")
BAR_MODULE_MM = 0.33  # a Code 128 module at its usual size
BAR_MODULE_MIN_MM = 0.19  # the narrowest a label printer still prints cleanly
QUIET_MODULES = 10


class CodeRenderer(Protocol):
    """Draws codes as inline SVG (no XML prolog, no fixed size: the label's CSS sizes it)."""

    def qr(self, content: str) -> str:  # noqa: D102 - see the class
        ...

    def code128(self, content: str, *, width_mm: float, height_mm: float) -> str:  # noqa: D102
        ...


class DefaultCodes:
    """segno for QR codes, python-barcode for Code 128; both pure Python, offline."""

    def qr(self, content: str) -> str:
        """A QR code (error correction M) with a viewBox only."""
        import segno  # noqa: PLC0415 - loaded with the first label

        code = segno.make(content, error="m", micro=False)
        svg: str = code.svg_inline(scale=1, border=2, omitsize=True)
        return svg

    def code128(self, content: str, *, width_mm: float, height_mm: float) -> str:
        """A Code 128 barcode that fits `width_mm`, without its text (printed beside it)."""
        from barcode import Code128  # noqa: PLC0415 - loaded with the first label
        from barcode.writer import SVGWriter  # noqa: PLC0415

        barcode = Code128(content, writer=SVGWriter())
        modules = len(barcode.build()[0]) + 2 * QUIET_MODULES
        module = max(BAR_MODULE_MIN_MM, min(BAR_MODULE_MM, width_mm / modules))
        raw = barcode.render(
            {
                "module_width": module,
                "module_height": height_mm,
                "quiet_zone": QUIET_MODULES * module,
                "write_text": False,
                "compress": False,
            }
        )
        svg = _PROLOG.sub("", raw.decode("utf-8"), count=1)
        width = modules * module
        height = height_mm + 2  # python-barcode keeps 1 mm above and below the bars
        # The root's fixed mm size goes; a viewBox in mm keeps the bars' proportions in the
        # label's box. Inside, the bars' lengths are in mm too: plain numbers in that viewBox.
        root = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.3f} {height:.3f}">'
        return _ROOT.sub(root, svg, count=1).replace("mm", "")


def _css(layout: LabelLayout) -> str:
    size = LAYOUTS[layout]
    return f"""
{pdf.font_faces()}
@page {{ size: {size.width_mm}mm {size.height_mm}mm; margin: 1.5mm; }}
html, body {{ margin: 0; padding: 0; }}
body {{ font-family: "{pdf.SANS}", "{pdf.NASKH}"; font-size: 7pt; color: #000; }}
.label {{ display: flex; align-items: center; gap: 2mm; height: {size.height_mm - 3}mm;
  page-break-after: always; overflow: hidden; }}
.label:last-child {{ page-break-after: auto; }}
.qr {{ flex: 0 0 auto; width: {size.code_mm}mm; height: {size.code_mm}mm; }}
.qr svg {{ width: 100%; height: 100%; }}
.bar {{ flex: 0 0 auto; width: {size.width_mm * 0.55:.1f}mm; height: {size.code_mm}mm; }}
.bar svg {{ width: 100%; height: 100%; }}
.text {{ flex: 1 1 auto; min-width: 0; }}
.title {{ font-weight: bold; font-size: 8pt; margin: 0 0 1mm; overflow-wrap: anywhere; }}
.caption {{ font-size: 8pt; margin: 0; overflow-wrap: anywhere; }}
"""


def labels_html(
    labels: Sequence[Label],
    *,
    layout: LabelLayout,
    symbology: Symbology,
    language: str,
    codes: CodeRenderer,
) -> str:
    """The labels' HTML: one page each, every text escaped, codes as inline SVG."""
    size = LAYOUTS[layout]
    direction = "rtl" if language in RTL_LANGUAGES else "ltr"
    pages: list[str] = []
    for label in labels:
        if symbology is Symbology.QR:
            code = f'<div class="qr">{codes.qr(label.content)}</div>'
        else:
            bar = codes.code128(
                label.content, width_mm=size.width_mm * 0.55, height_mm=size.code_mm
            )
            code = f'<div class="bar">{bar}</div>'
        title = ""
        if size.shows_name and label.title:
            title = f'<p class="title" dir="auto"><bdi>{escape(label.title)}</bdi></p>'
        caption = f'<p class="caption" dir="ltr"><bdi>{escape(label.caption)}</bdi></p>'
        pages.append(
            f'<section class="label">{code}<div class="text">{title}{caption}</div></section>'
        )
    return (
        f'<!doctype html><html lang="{escape(language)}" dir="{direction}"><head>'
        f'<meta charset="utf-8"><title>labels</title><style>{_css(layout)}</style></head>'
        f"<body>{''.join(pages)}</body></html>"
    )


# The shared renderer by default; tests may pass another (the PDF needs the worker image).
Render = Callable[..., bytes]


def render_labels(  # noqa: PLR0913 - the labels and how they are printed, explicit
    labels: Sequence[Label],
    *,
    layout: LabelLayout,
    symbology: Symbology,
    language: str,
    codes: CodeRenderer | None = None,
    fetcher: Any = None,  # noqa: ANN401 - a WeasyPrint URL fetcher (app/shared/pdf)
) -> bytes:
    """The labels' PDF within the label caps (pdf.PdfTooLarge beyond them)."""
    html = labels_html(
        labels,
        layout=layout,
        symbology=symbology,
        language=language,
        codes=codes or DefaultCodes(),
    )
    return pdf.render(html, fetcher, max_pages=PAGES_MAX, max_bytes=BYTES_MAX)
