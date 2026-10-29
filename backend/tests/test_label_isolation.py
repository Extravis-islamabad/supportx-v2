"""The isolation rule (2026-10-29): the server fills labels exactly as the console does.

The shared cases file is the contract for both sides (the console's isolation.test.ts reads it
too). Mail and files take `plain_label` (no marks) and `html_label` (<bdi>). The console's
right-to-left ranges must be the ones Python's Unicode data gives.
"""

import json
from pathlib import Path

import pytest

from app.shared.labels import html_label, isolate, label, plain_label, strip_isolates

CASES = json.loads(
    (
        Path(__file__).resolve().parents[2] / "frontend/packages/labels/src/isolation-cases.json"
    ).read_text(encoding="utf-8")
)["cases"]
MARKS = ("\u2066", "\u2067", "\u2068", "\u2069")


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c['key']}-{c['locale']}")
def test_the_server_matches_the_console(case: dict[str, object]) -> None:
    params = case["params"]
    assert isinstance(params, dict)
    assert label(str(case["key"]), str(case["locale"]), **params) == case["text"]


def test_mail_subjects_and_plain_text_carry_no_marks() -> None:
    for language in ("en", "ar", "ur"):
        subject = plain_label("mailbox_answer.follow_up.subject", language, id="INC-8", subject="x")
        body = plain_label("mail.waiting.from", language, sender="a@b.test", when="29/10")
        assert not any(mark in subject + body for mark in MARKS)
    marked = plain_label("auth.tenant_switched", "en", tenant="\u2068Other\u2069")
    assert marked == "You are now working in Other."


def test_the_html_part_isolates_with_bdi_and_escapes() -> None:
    html = html_label("mail.waiting.from", "ar", sender="<x>@b.test", when="29/10")
    assert str(html) == "من <bdi>&lt;x&gt;@b.test</bdi> · <bdi>29/10</bdi>"
    assert "INC-12" in str(html_label("notification.open_record", "en", id="INC-12"))
    assert "<bdi>INC-12" not in str(html_label("notification.open_record", "en", id="INC-12"))


def test_numbers_ids_and_isolated_values_are_left_alone() -> None:
    assert isolate(5, "ar") == "5"
    assert isolate("[INC-12]", "ar") == "[INC-12]"
    assert isolate("\u2068x\u2069", "ar") == "\u2068x\u2069"
    assert isolate("Other Company", "en") == "Other Company"  # same direction: no marks
    assert isolate("علي", "en") == "\u2068علي\u2069"
    assert strip_isolates("\u2068INC-12\u2069") == "INC-12"


def test_the_consoles_right_to_left_ranges_match_pythons_unicode_data() -> None:
    """The console can't ask a regex for a bidi class; its ranges file must equal ours."""
    from tooling.rtl_ranges import document  # noqa: PLC0415 - this test only

    shipped = json.loads(
        (
            Path(__file__).resolve().parents[2] / "frontend/packages/labels/src/rtl-ranges.json"
        ).read_text(encoding="utf-8")
    )
    assert shipped["ranges"] == document()["ranges"], "run `make labels-json`"
