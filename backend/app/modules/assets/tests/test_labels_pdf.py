"""Label PDFs through the shared renderer (REQ-AST-039 AC1; D-100 D8 holds for labels too).

Needs WeasyPrint and Pango: `uv sync --group pdf` locally (macOS: `make backend-test-pdf`), the
worker image in CI. Skipped where they are missing, unless SUPPORTX_REQUIRE_PDF_TESTS=1.
"""

import io
import os
import uuid

import pytest

from app.modules.assets.domain.labels import LabelLayout, Symbology, asset_label, vendor_label

pytestmark = pytest.mark.pdf


def _require_pdf() -> None:
    from app.shared import pdf  # noqa: PLC0415 - loads anywhere; renders where it can

    if not pdf.available():
        if os.environ.get("SUPPORTX_REQUIRE_PDF_TESTS") == "1":
            pytest.fail("PDF tests are required here but WeasyPrint or Pango cannot load")
        pytest.skip("WeasyPrint/Pango not installed (uv sync --group pdf)")


def _pages(data: bytes) -> int:
    from pypdf import PdfReader  # noqa: PLC0415 - test helper of the pdf group

    return len(PdfReader(io.BytesIO(data)).pages)


def _text(data: bytes) -> str:
    from pypdf import PdfReader  # noqa: PLC0415 - test helper of the pdf group

    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


def test_039_ac1_one_hundred_assets_make_one_printable_pdf() -> None:
    _require_pdf()
    from app.modules.assets.infra.labels import render_labels  # noqa: PLC0415

    labels = [
        asset_label(
            "https://desk.example.com/",
            uuid.uuid4(),
            tag=f"AST-{n}",
            name=f"Laptop {n}",
            symbology=Symbology.QR,
        )
        for n in range(100)
    ]
    data = render_labels(labels, layout=LabelLayout.LAPTOP, symbology=Symbology.QR, language="en")
    assert data.startswith(b"%PDF")
    assert _pages(data) == 100  # one label per page: the printer cuts them apart
    assert "AST-99" in _text(data)


def test_arabic_names_and_barcodes_render_and_nothing_is_fetched() -> None:
    _require_pdf()
    from app.modules.assets.infra.labels import render_labels  # noqa: PLC0415
    from app.shared.pdf import report_fetcher  # noqa: PLC0415

    fetcher = report_fetcher()
    labels = [
        asset_label(
            "https://d/",
            uuid.uuid4(),
            tag="AST-1",
            name="حاسوب محمول",
            symbology=Symbology.CODE128,
        ),
        vendor_label('<img src="http://169.254.169.254/x">'),
    ]
    data = render_labels(
        labels, layout=LabelLayout.CABLE, symbology=Symbology.CODE128, language="ar",
        fetcher=fetcher,
    )  # fmt: skip
    assert _pages(data) == 2
    assert fetcher.refused == []  # escaped text and inline SVG: nothing even asked for
    laptop = render_labels(
        labels[:1], layout=LabelLayout.LAPTOP, symbology=Symbology.QR, language="ar"
    )
    assert "حاسوب" in _text(laptop)


def test_labels_have_their_own_caps() -> None:
    _require_pdf()
    from app.modules.assets.infra import labels as module  # noqa: PLC0415
    from app.shared import pdf  # noqa: PLC0415
    from app.shared.pdf import PdfTooLarge  # noqa: PLC0415

    one = [vendor_label("SN-1")]
    with pytest.raises(PdfTooLarge) as caught:
        pdf.render(
            module.labels_html(
                one * 3, layout=LabelLayout.CABLE, symbology=Symbology.QR, language="en",
                codes=module.DefaultCodes(),
            ),
            max_pages=2,
        )  # fmt: skip
    assert caught.value.limit == "pages"
    with pytest.raises(PdfTooLarge) as caught:
        pdf.render(
            module.labels_html(
                one, layout=LabelLayout.CABLE, symbology=Symbology.QR, language="en",
                codes=module.DefaultCodes(),
            ),
            max_bytes=100,
        )  # fmt: skip
    assert caught.value.limit == "bytes"
