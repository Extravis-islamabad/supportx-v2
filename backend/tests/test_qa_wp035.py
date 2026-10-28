"""WP-035 QA findings (~/Desktop/qa-wp035/QA-REPORT.md), one test per ID, no database.

Exports name fields and values on the server (ADR-034); these tests pin the words and the text
direction of every export path, so a finding cannot come back in another file type.
"""

import re
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from app.modules.analytics.domain.tables import CellKind, Column, PdfInput
from app.modules.analytics.infra.pdf import report_html
from app.modules.analytics.infra.svgchart import chart_html
from app.modules.analytics.service.exports import RECORD_FIELDS
from app.modules.analytics.service.naming import field_label
from app.modules.work_items.service.access import FIELDS
from app.modules.work_items.service.reporting import DIMENSIONS
from app.shared.labels import FSI, LANGUAGES, PDI, label

UNKNOWN = {label("reports.unknown_value", language) for language in LANGUAGES}


@pytest.mark.parametrize("language", LANGUAGES)
def test_bug_01_every_export_header_has_a_proper_label(language: str) -> None:
    # Every field a records export lists, every grouping, and every filter field of incidents.
    names = {*RECORD_FIELDS["incident"], *DIMENSIONS, *FIELDS.fields}
    unknown = sorted(n for n in names if field_label(n, language, {}) in UNKNOWN)
    assert unknown == []


# --- BUG-02: words on a chart are laid out by the text engine, never drawn as SVG text ----------

KINDS = ("bar", "stacked_bar", "line", "area", "doughnut", "gauge", "kpi", "table")
ARABIC = ["غير محدد", "QA35 Alpha", "الدعم الفني - الرياض"]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("rtl", [True, False])
def test_bug_02_chart_words_are_html_with_an_explicit_direction(kind: str, rtl: bool) -> None:
    html = chart_html(kind, ARABIC, [5.0, 4.0, None], rtl=rtl, series_name="الحوادث")
    svg = re.findall(r"<svg.*?</svg>", html, flags=re.DOTALL)
    for part in svg:  # SVG text has no bidi or shaping in WeasyPrint: digits only there
        assert not re.search(r"<text[^>]*>[^<]*[^\d\s.,%<-][^<]*</text>", part), part
    words = re.sub(r"<svg.*?</svg>", "", html, flags=re.DOTALL)
    direction = "rtl" if rtl else "ltr"
    for name in ARABIC:
        assert escape(name) in words or "…" in words
    assert f'dir="{direction}"' in words
    for element in re.findall(r"<(?:span|li|div)[^>]*>[^<]*[^\W\d_][^<]*<", words):
        assert "<bdi" in element or 'dir="' in element or "auto" in element, element


# --- BUG-04: values in right-to-left text keep their own order -----------------------------------


def test_bug_04_values_in_arabic_and_urdu_labels_are_isolated() -> None:
    for language in ("ar", "ur"):
        text = label("reports.export_run_at", language, time="2026-10-28 07:02")
        assert f"{FSI}2026-10-28 07:02{PDI}" in text
    assert FSI not in label("reports.export_run_at", "en", time="2026-10-28 07:02")


def test_bug_04_pdf_isolates_every_cell_including_totals() -> None:
    html = report_html(
        PdfInput(
            title="تقرير",
            language="ar",
            rtl=True,
            header_lines=["تقرير", label("reports.export_run_at", "ar", time="2026-10-28 07:02")],
            columns=[Column("المجموعة"), Column("الحوادث", CellKind.NUMBER)],
            rows=[["QA35 Alpha", 6]],
            totals=["الإجمالي", 6],
            chart=None,
            records_columns=[],
            records=[],
            records_cut=False,
        )
    )
    cells = re.findall(r"<td[^>]*>(.*?)</td>", html)
    assert cells
    assert all(c.startswith("<bdi>") for c in cells if c)
    assert f"{FSI}2026-10-28 07:02{PDI}" in html


# --- ENV-01: the dev worker can make PDFs ---------------------------------------------------------


def test_env_01_a_make_target_runs_the_consumers_with_pdf_exports() -> None:
    root = Path(__file__).resolve().parents[2]
    makefile = (root / "Makefile").read_text(encoding="utf-8")
    target = re.search(r"^worker-consumers-pdf:.*\n((?:\t.*\n)+)", makefile, flags=re.MULTILINE)
    assert target is not None
    recipe = target.group(1)
    assert "--group pdf" in recipe
    assert "workers.consumers" in recipe
    # Homebrew keeps glib outside /opt/homebrew/lib: WeasyPrint needs both on macOS.
    assert "opt/glib/lib" in makefile
    assert "make worker-consumers-pdf" in (root / "docs" / "dev-setup.md").read_text("utf-8")
