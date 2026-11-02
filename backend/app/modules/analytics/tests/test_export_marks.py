"""Exported files carry no directional marks (item 6a, on #132's isolation rule).

The words the server writes into a CSV, Excel or PDF export (header lines, column headers, value
names) are filled labels. On screen a filled value is wrapped in FSI…PDI in Arabic and Urdu; in a
file those invisible characters would end up in every cell a reader copies, sorts or matches on.
"""

import csv
import io
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from openpyxl import load_workbook

from app.modules.analytics.domain.definition import DateBucket
from app.modules.analytics.domain.measures import Better, MeasureKind, MeasureSpec, Unit
from app.modules.analytics.domain.tables import CellKind, Column, ExportDocument, Sheet
from app.modules.analytics.infra.writers import csv_chunks, xlsx_bytes
from app.modules.analytics.service.exports import FileSpec, _header_lines, _measure_header
from app.modules.analytics.service.naming import _bucket_text, field_label
from app.shared.labels import label

# Every bidi control: embeddings, overrides, isolates and the LRM/RLM/ALM marks.
MARKS = {chr(c) for c in (0x200E, 0x200F, 0x061C, *range(0x202A, 0x202F), *range(0x2066, 0x206A))}
RTL = ("ar", "ur")
ZONE = ZoneInfo("Asia/Karachi")
HOURS = MeasureSpec(
    "mean_time_to_resolve",
    MeasureKind.AVERAGE_DURATION,
    Unit.SECONDS,
    Better.DOWN,
    start="created_at",
    end="resolved_at",
)


def _marked(texts: list[str]) -> list[str]:
    return [text for text in texts if MARKS & set(text)]


def _words(language: str) -> list[str]:
    spec = cast("FileSpec", SimpleNamespace(language=language, title="Open incidents"))
    ran_at = datetime(2026, 11, 2, 9, 30, tzinfo=UTC)
    return [
        *_header_lines(spec, ran_at, ZONE),
        _measure_header("incident", HOURS, language),
        _bucket_text(DateBucket.WEEK, date(2026, 10, 26), language),
        _bucket_text(DateBucket.QUARTER, date(2026, 10, 26), language),
        field_label("custom.vendor", language, {"custom.vendor": "Vendor"}),
    ]


@pytest.mark.parametrize("language", RTL)
def test_the_screen_would_isolate_these_values(language: str) -> None:
    # The guard is real: the on-screen label marks the same filled value in a right-to-left text.
    assert _marked([label("reports.times_in", language, zone=ZONE.key)])


@pytest.mark.parametrize("language", [*RTL, "en"])
def test_export_words_carry_no_directional_marks(language: str) -> None:
    assert _marked(_words(language)) == []


@pytest.mark.parametrize("language", RTL)
def test_no_cell_of_a_csv_or_excel_export_has_a_mark(language: str) -> None:
    words = _words(language)
    sheet = Sheet(
        name="Summary",
        columns=[
            Column(words[4]),
            Column(_measure_header("incident", HOURS, language), CellKind.HOURS),
        ],
        header_lines=words[:4],
    )
    sheet.add([words[5], 7200])
    sheet.add([words[6], 3600])
    document = ExportDocument(title="Open incidents", language=language, rtl=True, sheets=[sheet])

    text = b"".join(csv_chunks(document)).decode("utf-8-sig")
    cells = [cell for row in csv.reader(io.StringIO(text)) for cell in row]
    assert cells
    assert _marked(cells) == []

    workbook = load_workbook(io.BytesIO(xlsx_bytes(document)))
    values = [str(c.value) for ws in workbook for row in ws.iter_rows() for c in row if c.value]
    assert values
    assert _marked(values) == []
