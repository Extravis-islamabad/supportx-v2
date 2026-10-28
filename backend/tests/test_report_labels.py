"""Every built-in report, report folder, measure, ageing bucket and widget has a label.

WP-035; the widget catalogue's titles, descriptions, sections and "coming with" notes (D-114).

REQ-DSH-045 AC1: built-in report names and measure definitions in English and Arabic, CI fails
if one is missing; Urdu is checked too (D-033: every new string).
"""

import pytest

from app.modules.analytics.domain.builtin import BUILTIN_REPORTS
from app.modules.analytics.domain.definition import AGE_BUCKETS
from app.modules.analytics.domain.measures import FLOW, MEASURES
from app.modules.analytics.domain.widgets import CATALOGUE, SECTIONS
from tests.test_error_labels import label_keys


def _needed() -> set[str]:
    keys = {f"report.{r.code}" for r in BUILTIN_REPORTS}
    keys |= {f"report.{r.code}.description" for r in BUILTIN_REPORTS}
    keys |= {f"report_folder.{r.folder}" for r in BUILTIN_REPORTS}
    keys |= {f"age_bucket.{code}" for code, _low, _high in AGE_BUCKETS}
    for entity, measures in MEASURES.items():
        for code in measures:
            keys |= {f"measure.{entity}.{code}", f"measure.{entity}.{code}.help"}
    keys |= {f"measure.incident.{code}" for code in FLOW}
    keys |= {f"measure.incident.{code}.help" for code in FLOW}
    for template in CATALOGUE.values():
        title = template.title_key or f"dashboard_widget.{template.code}"
        keys |= {title, f"{title}.description"}
        if template.coming_with is not None:
            keys.add(f"widget_coming.{template.coming_with}")
    keys |= {f"widget_section.{code}" for code in SECTIONS}
    return keys


@pytest.mark.parametrize("locale", ["en", "ar", "ur"])
def test_every_report_label_exists(locale: str) -> None:
    missing = sorted(_needed() - set(label_keys(locale)))
    assert missing == [], f"add these keys to packages/labels/src/resources/{locale}.ts"
