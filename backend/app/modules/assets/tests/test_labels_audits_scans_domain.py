"""Labels, audits and scans as pure rules (WP-049b s3; REQ-AST-039, 042, 043, 054, 056)."""

import uuid

import pytest

from app.modules.assets.domain.audits import (
    AuditItemKind,
    AuditItemResult,
    is_discrepancy,
    plan_problems,
    result_of,
)
from app.modules.assets.domain.labels import (
    LABELS_MAX,
    LabelLayout,
    Symbology,
    asset_label,
    asset_link,
    clean_codes,
    vendor_label,
)
from app.modules.assets.domain.scans import (
    ChangeKind,
    HardwareCategory,
    OverdueAction,
    ScanFailure,
    ScanProblem,
    ScanResult,
    clean_change,
    clean_changes,
    failure_problem,
    rule_problems,
)
from app.modules.assets.infra.labels import DefaultCodes, labels_html

ASSET = uuid.UUID("01900000-0000-7000-8000-000000000001")
SITE_A = uuid.uuid4()
SITE_B = uuid.uuid4()


def test_039_ac2_the_qr_code_holds_only_the_console_link() -> None:
    label = asset_label(
        "https://desk.example.com/",
        ASSET,
        tag="AST-7",
        name="Finance laptop",
        symbology=Symbology.QR,
    )
    assert label.content == f"https://desk.example.com/assets/{ASSET}"
    assert "AST-7" not in label.content
    assert "Finance" not in label.content
    assert asset_link("https://x/console/", ASSET) == f"https://x/console/assets/{ASSET}"


def test_a_barcode_holds_the_tag_and_vendor_codes_are_printed_as_typed() -> None:
    bar = asset_label("https://d/", ASSET, tag="AST-7", name="X", symbology=Symbology.CODE128)
    assert (bar.content, bar.caption) == ("AST-7", "AST-7")
    assert vendor_label("SN-123").content == "SN-123"
    assert clean_codes(["  SN  1 ", "", "SN-2"]) == (["SN 1", "SN-2"], None)
    assert clean_codes([" "]) == ([], "required")
    assert clean_codes(["x" * 121]) == ([], "value_too_long")
    assert clean_codes(["a\x00b"]) == ([], "invalid_value")
    assert clean_codes(["c"] * (LABELS_MAX + 1)) == ([], "too_many")


def test_label_html_escapes_text_and_runs_right_to_left_in_arabic() -> None:
    label = asset_label(
        "https://d/", ASSET, tag="AST-7", name="<b>حاسوب</b>", symbology=Symbology.QR
    )
    html = labels_html(
        [label], layout=LabelLayout.LAPTOP, symbology=Symbology.QR, language="ar",
        codes=DefaultCodes(),
    )  # fmt: skip
    assert 'dir="rtl"' in html
    assert "<b>" not in html
    assert "&lt;b&gt;" in html
    assert "<bdi>AST-7</bdi>" in html  # the Latin tag keeps its order beside Arabic text
    assert "http" not in html.split("<body>", 1)[1].replace("http://www.w3.org/2000/svg", "")
    cable = labels_html(
        [label], layout=LabelLayout.CABLE, symbology=Symbology.CODE128, language="en",
        codes=DefaultCodes(),
    )  # fmt: skip
    assert "حاسوب" not in cable  # the cable label shows the code and the tag only
    assert "<?xml" not in cable


def test_043_ac1_found_at_another_site_is_the_wrong_place() -> None:
    found = AuditItemResult.FOUND
    assert result_of(found, expected_site=SITE_A, seen_site=SITE_B) is AuditItemResult.WRONG_PLACE
    assert result_of(found, expected_site=SITE_A, seen_site=SITE_A) is AuditItemResult.FOUND
    assert result_of(found, expected_site=SITE_A, seen_site=None) is AuditItemResult.FOUND
    damaged = AuditItemResult.DAMAGED
    assert result_of(damaged, expected_site=SITE_A, seen_site=SITE_B) is AuditItemResult.DAMAGED


def test_discrepancies_and_plans() -> None:
    expected, unexpected = AuditItemKind.EXPECTED, AuditItemKind.UNEXPECTED
    assert not is_discrepancy(expected, AuditItemResult.FOUND, closed=True)
    assert is_discrepancy(expected, AuditItemResult.MISSING, closed=False)
    assert is_discrepancy(unexpected, AuditItemResult.FOUND, closed=False)
    assert not is_discrepancy(expected, None, closed=False)
    assert is_discrepancy(expected, None, closed=True)
    from datetime import date  # noqa: PLC0415 - only here

    assert plan_problems(" ", None, None) == [("name", "required")]
    assert plan_problems("Q4", date(2026, 12, 2), date(2026, 12, 1)) == [
        ("planned_end", "end_before_start")
    ]


def test_054_ac1_a_new_disk_is_a_labelled_change_with_its_model_and_capacity() -> None:
    change = clean_change(
        {"kind": "hardware_added", "category": "disk", "name": "NVMe", "model": "MZ-V8V1T0",
         "capacity": "1 TB", "blob": "x" * 5000}
    )  # fmt: skip
    assert change.kind is ChangeKind.HARDWARE_ADDED
    assert change.category is HardwareCategory.DISK
    assert change.as_json() == {
        "kind": "hardware_added", "category": "disk", "name": "NVMe", "model": "MZ-V8V1T0",
        "capacity": "1 TB",
    }  # fmt: skip
    software = clean_change({"kind": "software_removed", "name": "7-Zip", "version": "23"})
    assert software.as_json() == {"kind": "software_removed", "name": "7-Zip", "version": "23"}
    for bad in ({"kind": "rebooted", "name": "x"}, {"kind": "hardware_added"}):
        with pytest.raises(ScanProblem):
            clean_change(bad)
    with pytest.raises(ScanProblem):
        clean_changes([{"kind": "software_installed", "name": "x"}] * 2001)


def test_054_ac3_a_failed_scan_says_why_and_rules_need_a_state() -> None:
    assert failure_problem(ScanResult.FAILED, None) is not None
    assert failure_problem(ScanResult.FAILED, ScanFailure.UNREACHABLE) is None
    assert failure_problem(ScanResult.OK, ScanFailure.OTHER) is not None
    assert rule_problems(enabled=True, days=60, action=OverdueAction.MOVE_STATE, state_id=None) == [
        ("state_id", "required")
    ]
    assert rule_problems(enabled=True, days=60, action=OverdueAction.TRASH, state_id=None) == []
    assert rule_problems(enabled=False, days=0, action=OverdueAction.TRASH, state_id=None) == [
        ("days", "out_of_range")
    ]
