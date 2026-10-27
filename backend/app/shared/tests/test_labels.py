"""Server-side labels (D-100 D7, ADR-034)."""

import json
from pathlib import Path

import pytest

from app.shared import labels
from app.shared.labels import MissingLabelError, has_label, label, plural_category
from tests.test_error_labels import label_keys


def test_the_json_copy_has_every_key_of_the_label_resources() -> None:
    # The frontend test checks values too; this one keeps a backend-only change honest.
    exported = json.loads(Path(labels.__file__).with_name("resources.json").read_text("utf-8"))
    for language in ("en", "ar", "ur"):
        missing = sorted(label_keys(language) - set(exported[language]))
        assert missing == [], "run `make labels-json`"
    assert has_label("report.incidents_all")


def test_label_in_each_language_with_english_fallback_and_params() -> None:
    assert label("priority.p1", "en") != "p1"
    assert label("report.incidents_all", "ar") == "جميع الحوادث"
    assert label("report.incidents_all", "de") == "All incidents"  # unknown language: English
    assert label("errors.report_timeout", "en", seconds=30).startswith(
        "The report took longer than 30 seconds"
    )
    with pytest.raises(MissingLabelError):
        label("no.such.key", "en")


@pytest.mark.parametrize(
    ("language", "count", "category"),
    [
        ("en", 1, "one"),
        ("en", 2, "other"),
        ("ar", 0, "zero"),
        ("ar", 2, "two"),
        ("ar", 5, "few"),
        ("ar", 15, "many"),
        ("ar", 100, "other"),
        ("ur", 1, "one"),
    ],
)
def test_plural_categories(language: str, count: int, category: str) -> None:
    assert plural_category(language, count) == category
