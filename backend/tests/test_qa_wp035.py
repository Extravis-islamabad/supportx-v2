"""WP-035 QA findings (~/Desktop/qa-wp035/QA-REPORT.md), one test per ID, no database.

Exports name fields and values on the server (ADR-034); these tests pin the words and the text
direction of every export path, so a finding cannot come back in another file type.
"""

import pytest

from app.modules.analytics.service.exports import RECORD_FIELDS
from app.modules.analytics.service.naming import field_label
from app.modules.work_items.service.access import FIELDS
from app.modules.work_items.service.reporting import DIMENSIONS
from app.shared.labels import LANGUAGES, label

UNKNOWN = {label("reports.unknown_value", language) for language in LANGUAGES}


@pytest.mark.parametrize("language", LANGUAGES)
def test_bug_01_every_export_header_has_a_proper_label(language: str) -> None:
    # Every field a records export lists, every grouping, and every filter field of incidents.
    names = {*RECORD_FIELDS["incident"], *DIMENSIONS, *FIELDS.fields}
    unknown = sorted(n for n in names if field_label(n, language, {}) in UNKNOWN)
    assert unknown == []
