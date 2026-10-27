"""PDF exports with WeasyPrint (REQ-RPT-058, REQ-DSH-046; D-100 D8).

Only the worker image installs WeasyPrint (dependency group `pdf`). This module imports it only
inside the functions that render, so it loads anywhere (the API image, test discovery) and
`available()` says whether this process can render. Arabic and Urdu are shaped by
Pango/HarfBuzz and laid out right to left with the bundled Noto fonts.

D-100 D8 conditions:
- The URL fetcher refuses everything except the bundled fonts: no network, no other file path.
  Report content cannot add URLs anyway (every text is HTML-escaped and the chart is inline
  SVG), and the fetcher makes that hold even if a template bug ever let one through.
- Fonts come from this package, so the PDF looks the same offline and air-gapped.
"""

import datetime as dt
from functools import cache
from html import escape
from pathlib import Path
from typing import Any
from urllib.request import url2pathname

from app.modules.analytics.domain.tables import CellKind, Column, PdfInput, Value
from app.modules.analytics.infra.svgchart import chart_svg
from app.shared.labels import label

FONTS = (Path(__file__).resolve().parent / "fonts").resolve()
_FONT_FILES = {
    "sans": "NotoSans-Regular.ttf",
    "sans-bold": "NotoSans-Bold.ttf",
    "naskh": "NotoNaskhArabic-Regular.ttf",
    "naskh-bold": "NotoNaskhArabic-Bold.ttf",
}


class RefusedURL(ValueError):
    """A resource the PDF may not load."""


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


def _font_faces() -> str:
    faces = [
        ("SupportX Sans", "sans", "normal"),
        ("SupportX Sans", "sans-bold", "bold"),
        ("SupportX Naskh", "naskh", "normal"),
        ("SupportX Naskh", "naskh-bold", "bold"),
    ]
    return "\n".join(
        f'@font-face {{ font-family: "{family}"; font-weight: {weight}; '
        f'src: url("{(FONTS / _FONT_FILES[key]).as_uri()}"); }}'
        for family, key, weight in faces
    )


def _cell(column: Column, value: Value) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if column.kind == CellKind.PERCENT and isinstance(value, int | float):
        return f"{value:.1f}%"
    if column.kind == CellKind.HOURS and isinstance(value, int | float):
        return f"{value / 3600:.2f}"
    return str(value)


def _table(columns: list[Column], rows: list[list[Value]], totals: list[Value] | None) -> str:
    def numeric(column: Column) -> str:
        return ' class="num"' if column.kind != CellKind.TEXT else ""

    head = "".join(f"<th{numeric(c)}>{escape(c.header)}</th>" for c in columns)
    body = "".join(
        "<tr>"
        + "".join(
            f"<td{numeric(c)}><bdi>{escape(_cell(c, v))}</bdi></td>"
            for c, v in zip(columns, row, strict=True)
        )
        + "</tr>"
        for row in rows
    )
    foot = ""
    if totals is not None:
        foot = (
            "<tfoot><tr>"
            + "".join(
                f"<td{numeric(c)}>{escape(_cell(c, v))}</td>"
                for c, v in zip(columns, totals, strict=True)
            )
            + "</tr></tfoot>"
        )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody>{foot}</table>"


def report_html(data: PdfInput) -> str:
    """The PDF's HTML: every text escaped, the chart inline, nothing to fetch but fonts."""
    direction = "rtl" if data.rtl else "ltr"
    lines = "".join(f"<p class='meta'>{escape(line)}</p>" for line in data.header_lines[1:])
    chart = ""
    if data.chart is not None:
        chart = (
            "<figure>"
            + chart_svg(data.chart.kind, data.chart.categories, data.chart.values, rtl=data.rtl)
            + f"<figcaption>{escape(data.chart.series_name)}</figcaption></figure>"
        )
    records = ""
    if data.records:
        records = f"<h2>{escape(label('reports.sheet_records', data.language))}</h2>" + _table(
            data.records_columns, data.records, None
        )
        if data.records_cut:
            records += (
                f"<p class='meta'>{escape(label('reports.pdf_records_cut', data.language))}</p>"
            )
    css = f"""
{_font_faces()}
@page {{ size: A4 landscape; margin: 14mm;
  @bottom-center {{ content: counter(page) " / " counter(pages); font-size: 8pt; }} }}
body {{ font-family: "SupportX Sans", "SupportX Naskh"; font-size: 9pt; }}
h1 {{ font-size: 15pt; margin: 0 0 4pt; }}
h2 {{ font-size: 11pt; margin: 12pt 0 4pt; }}
.meta {{ color: #595959; margin: 0 0 2pt; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 8pt; }}
th, td {{ border-bottom: 0.5pt solid #d9d9d9; padding: 3pt 4pt; text-align: start; }}
th {{ background: #fafafa; }}
.num {{ text-align: end; }}
tfoot td {{ font-weight: bold; }}
figure {{ margin: 8pt 0; }}
figcaption {{ color: #595959; }}
"""
    return (
        f'<!doctype html><html lang="{escape(data.language)}" dir="{direction}"><head>'
        f'<meta charset="utf-8"><title>{escape(data.title)}</title><style>{css}</style></head>'
        f"<body><h1>{escape(data.title)}</h1>{lines}{chart}"
        f"{_table(data.columns, data.rows, data.totals)}{records}</body></html>"
    )


def render_pdf(data: PdfInput, fetcher: Any = None) -> bytes:  # noqa: ANN401 - see report_fetcher
    """The PDF bytes of `data` (worker image only)."""
    from weasyprint import HTML  # noqa: PLC0415 - worker image only

    pdf: bytes = HTML(
        string=report_html(data),
        base_url=FONTS.as_uri() + "/",
        url_fetcher=fetcher or report_fetcher(),
    ).write_pdf()
    return pdf
