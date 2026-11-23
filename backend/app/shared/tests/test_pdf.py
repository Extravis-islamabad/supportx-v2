"""The shared PDF renderer's D-100 D8 conditions: only the bundled fonts, nothing else fetched.

Moved from analytics (WP-049b s3) with the renderer; report-only tests stay in analytics
(app/modules/analytics/tests/test_report_pdf.py).

Needs WeasyPrint and Pango: `uv sync --group pdf` locally (macOS: `make backend-test-pdf` sets the
Homebrew library path), the worker image in CI. Skipped where they are missing, unless
SUPPORTX_REQUIRE_PDF_TESTS=1 (the CI job in the worker image) turns that into a failure.
"""

import os
from types import ModuleType

import pytest

pytestmark = pytest.mark.pdf


def _pdf_module() -> ModuleType:
    from app.shared import pdf  # noqa: PLC0415 - loads anywhere; renders where it can

    if not pdf.available():
        if os.environ.get("SUPPORTX_REQUIRE_PDF_TESTS") == "1":
            pytest.fail("PDF tests are required here but WeasyPrint or Pango cannot load")
        pytest.skip("WeasyPrint/Pango not installed (uv sync --group pdf)")
    return pdf


def test_d100_the_fetcher_serves_only_the_bundled_fonts() -> None:
    pdf = _pdf_module()
    fetcher = pdf.report_fetcher()
    for url in (
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://127.0.0.1:8000/api/v1/users",  # the API itself
        "https://example.com/logo.png",
        "file:///etc/passwd",
        (pdf.FONTS / ".." / "__init__.py").resolve().as_uri(),  # outside the fonts folder
        "data:text/html,<script>alert(1)</script>",
    ):
        with pytest.raises(ValueError, match="refused"):
            fetcher.fetch(url)
    font = fetcher.fetch((pdf.FONTS / "NotoSans-Regular.ttf").as_uri())
    assert font.read(4) in {b"\x00\x01\x00\x00", b"true"}  # a TrueType file


def test_d100_a_url_in_markup_is_refused_by_the_fetcher_not_fetched() -> None:
    pdf = _pdf_module()
    from weasyprint import HTML  # noqa: PLC0415 - optional dependency

    fetcher = pdf.report_fetcher()
    HTML(
        string='<img src="http://169.254.169.254/x"><img src="file:///etc/hosts">',
        url_fetcher=fetcher,
    ).write_pdf()
    assert set(fetcher.refused) == {"http://169.254.169.254/x", "file:///etc/hosts"}
