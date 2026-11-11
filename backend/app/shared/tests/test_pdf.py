"""PDF exports (REQ-RPT-058, REQ-DSH-046) and the D-100 D8 conditions.

Needs WeasyPrint and Pango: `uv sync --group pdf` locally (macOS: `make backend-test-pdf` sets the
Homebrew library path), the worker image in CI. Skipped where they are missing, unless
SUPPORTX_REQUIRE_PDF_TESTS=1 (the CI job in the worker image) turns that into a failure.
"""

import io
import os
import re
from types import ModuleType
from typing import Any

import pytest

from app.modules.analytics.domain.tables import CellKind, ChartData, Column, PdfInput
from app.modules.analytics.infra.svgchart import chart_html, chart_svg

pytestmark = pytest.mark.pdf


def _pdf_module() -> ModuleType:
    from app.modules.analytics.infra import pdf  # noqa: PLC0415 - loads anywhere; renders where it can

    if not pdf.available():
        if os.environ.get("SUPPORTX_REQUIRE_PDF_TESTS") == "1":
            pytest.fail("PDF tests are required here but WeasyPrint or Pango cannot load")
        pytest.skip("WeasyPrint/Pango not installed (uv sync --group pdf)")
    return pdf


def _text(data: bytes) -> str:
    from pypdf import PdfReader  # noqa: PLC0415 - test helper of the pdf group

    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


def _fonts(data: bytes) -> list[str]:
    from pypdf import PdfReader  # noqa: PLC0415 - test helper of the pdf group

    names: list[str] = []
    for page in PdfReader(io.BytesIO(data)).pages:
        # Any: pypdf's object types differ with and without the optional package installed.
        resources: Any = page["/Resources"]
        fonts = resources["/Font"]
        names += [str(fonts[key].get_object()["/BaseFont"]) for key in fonts]
    return names


def _input(*, rtl: bool, title: str = "Open incidents by priority") -> PdfInput:
    return PdfInput(
        title=title,
        language="ar" if rtl else "en",
        rtl=rtl,
        header_lines=[title, "Times in Asia/Riyadh"],
        columns=[Column("الأولوية" if rtl else "Priority"), Column("Count", CellKind.NUMBER)],
        rows=[["عاجل جدًا" if rtl else "P1 - Critical", 8], ["INC-1042", 2]],
        totals=["الإجمالي" if rtl else "Total", 10],
        chart=ChartData("bar", ["P1", "P2"], [8.0, 2.0], "Count"),
        records_columns=[],
        records=[],
        records_cut=False,
    )


def test_req_dsh_046_arabic_pdf_is_shaped_right_to_left_with_the_bundled_font() -> None:
    pdf = _pdf_module()
    html = pdf.report_html(_input(rtl=True, title="الحوادث المفتوحة"))
    assert 'dir="rtl"' in html
    assert "<bdi>INC-1042</bdi>" in html  # Latin ids keep their order inside Arabic text
    data = pdf.render_pdf(_input(rtl=True, title="الحوادث المفتوحة"))
    assert data.startswith(b"%PDF")
    # The bundled Arabic font is embedded (subset), so Pango/HarfBuzz shaped the letters with it.
    assert any("SupportX-Naskh" in name for name in _fonts(data))
    text = _text(data)
    assert "الحوادث" in text  # the text maps back to the words, not to isolated glyph forms
    assert "10" in text


def test_d100_the_fetcher_serves_only_the_bundled_fonts() -> None:
    pdf = _pdf_module()
    fetcher = pdf.report_fetcher()
    for url in (
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://127.0.0.1:8000/api/v1/users",  # the API itself
        "https://example.com/logo.png",
        "file:///etc/passwd",
        (pdf.FONTS / ".." / "pdf.py").resolve().as_uri(),  # outside the fonts folder
        "data:text/html,<script>alert(1)</script>",
    ):
        with pytest.raises(ValueError, match="refused"):
            fetcher.fetch(url)
    font = fetcher.fetch((pdf.FONTS / "NotoSans-Regular.ttf").as_uri())
    assert font.read(4) in {b"\x00\x01\x00\x00", b"true"}  # a TrueType file


def test_d100_report_content_never_makes_the_pdf_fetch_anything() -> None:
    pdf = _pdf_module()
    hostile = (
        '<img src="http://169.254.169.254/x"><link rel=stylesheet href="http://10.0.0.1/s.css">'
        "<style>@import url(http://127.0.0.1:1/x.css);</style>"
    )
    fetcher = pdf.report_fetcher()
    data = pdf.render_pdf(_input(rtl=False, title=hostile), fetcher)
    assert fetcher.refused == []  # escaped text: nothing even asked for
    assert "169.254.169.254" in _text(data)  # shown as text, harmlessly


def test_d100_a_url_in_markup_is_refused_by_the_fetcher_not_fetched() -> None:
    pdf = _pdf_module()
    from weasyprint import HTML  # noqa: PLC0415 - optional dependency

    fetcher = pdf.report_fetcher()
    HTML(
        string='<img src="http://169.254.169.254/x"><img src="file:///etc/hosts">',
        url_fetcher=fetcher,
    ).write_pdf()
    assert set(fetcher.refused) == {"http://169.254.169.254/x", "file:///etc/hosts"}


def test_svg_chart_escapes_labels_and_mirrors_for_rtl() -> None:
    html = chart_html("bar", ["<b>P1</b>", "P2"], [3, None], rtl=False, series_name="n")
    assert "<b>" not in html
    assert "&lt;b&gt;P1" in html
    ltr = chart_svg("bar", [1, 2], rtl=False)
    rtl = chart_svg("bar", [1, 2], rtl=True)
    first_x = [float(m) for m in re.findall(r'<text x="([\d.]+)"[^>]*>1<', ltr)]
    first_x_rtl = [float(m) for m in re.findall(r'<text x="([\d.]+)"[^>]*>1<', rtl)]
    assert first_x[0] < first_x_rtl[0]  # the first category starts on the right in RTL
    assert 'dir="rtl"' in chart_html("bar", ["a"], [1], rtl=True, series_name="n")
    doughnut = chart_svg("doughnut", [1, 3], rtl=False)
    assert doughnut.count("<path") == 2
