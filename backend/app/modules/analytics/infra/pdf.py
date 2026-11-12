"""PDF exports of reports (REQ-RPT-058, REQ-DSH-046; D-100 D8).

The report's own HTML (tables, the inline SVG chart) is built here; rendering, the bundled fonts
and the fetcher that refuses every URL but those fonts are the shared renderer's
(app/shared/pdf, moved there in WP-049b s3 so asset labels use the same one). Only the worker
image renders: `available()` is the shared probe.
"""

import datetime as dt
from html import escape
from typing import Any

from app.modules.analytics.domain.tables import CellKind, Column, PdfInput, Value
from app.modules.analytics.infra.svgchart import chart_html
from app.shared import pdf as renderer
from app.shared.labels import plain_label as label
from app.shared.pdf import FONTS, RefusedURL, available, bundled_font, report_fetcher

__all__ = [
    "FONTS",
    "RefusedURL",
    "available",
    "bundled_font",
    "render_pdf",
    "report_fetcher",
    "report_html",
]


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

    head = "".join(f"<th{numeric(c)}><bdi>{escape(c.header)}</bdi></th>" for c in columns)
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
                f"<td{numeric(c)}><bdi>{escape(_cell(c, v))}</bdi></td>"
                for c, v in zip(columns, totals, strict=True)
            )
            + "</tr></tfoot>"
        )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody>{foot}</table>"


def report_html(data: PdfInput) -> str:
    """The PDF's HTML: every text escaped, the chart inline, nothing to fetch but fonts."""
    direction = "rtl" if data.rtl else "ltr"
    # Every text block states its direction; values inside labels are isolated (FSI/PDI, filled
    # by `label`), so dates and Latin names keep their order in Arabic (QA WP-035 BUG-04).
    lines = "".join(
        f"<p class='meta' dir='{direction}'>{escape(line)}</p>" for line in data.header_lines[1:]
    )
    chart = ""
    if data.chart is not None:
        chart = chart_html(
            data.chart.kind,
            data.chart.categories,
            data.chart.values,
            rtl=data.rtl,
            series_name=data.chart.series_name,
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
{renderer.font_faces()}
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
.cats {{ display: flex; font-size: 7.5pt; color: #434343; }}
.cat {{ flex: 1 1 0; text-align: center; padding: 2pt 2pt 0; overflow-wrap: anywhere; }}
.pie {{ display: flex; align-items: center; gap: 16pt; }}
.slices {{ list-style: none; margin: 0; padding: 0; }}
.slices li {{ margin: 0 0 3pt; }}
.swatch {{ display: inline-block; width: 8pt; height: 8pt; margin-inline-end: 4pt; }}
"""
    return (
        f'<!doctype html><html lang="{escape(data.language)}" dir="{direction}"><head>'
        f'<meta charset="utf-8"><title>{escape(data.title)}</title><style>{css}</style></head>'
        f"<body><h1><bdi>{escape(data.title)}</bdi></h1>{lines}{chart}"
        f"{_table(data.columns, data.rows, data.totals)}{records}</body></html>"
    )


def render_pdf(data: PdfInput, fetcher: Any = None) -> bytes:  # noqa: ANN401 - see report_fetcher
    """The PDF bytes of `data` (worker image only)."""
    return renderer.render(report_html(data), fetcher)
