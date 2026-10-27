"""Every built-in report, report folder, measure and ageing bucket has a label (WP-035).

REQ-DSH-045 AC1: built-in report names and measure definitions in English and Arabic, CI fails
if one is missing; Urdu is checked too (D-033: every new string).
"""

import pytest

from app.modules.analytics.domain.builtin import BUILTIN_REPORTS
from app.modules.analytics.domain.definition import AGE_BUCKETS
from app.modules.analytics.domain.measures import MEASURES
from tests.test_error_labels import label_keys


def _needed() -> set[str]:
    keys = {f"report.{r.code}" for r in BUILTIN_REPORTS}
    keys |= {f"report.{r.code}.description" for r in BUILTIN_REPORTS}
    keys |= {f"report_folder.{r.folder}" for r in BUILTIN_REPORTS}
    keys |= {f"age_bucket.{code}" for code, _low, _high in AGE_BUCKETS}
    for entity, measures in MEASURES.items():
        for code in measures:
            keys |= {f"measure.{entity}.{code}", f"measure.{entity}.{code}.help"}
    return keys


@pytest.mark.parametrize("locale", ["en", "ar", "ur"])
def test_every_report_label_exists(locale: str) -> None:
    missing = sorted(_needed() - set(label_keys(locale)))
    assert missing == [], f"add these keys to packages/labels/src/resources/{locale}.ts"
