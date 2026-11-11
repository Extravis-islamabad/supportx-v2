"""Bulk changes, merge suggestions, import reading (WP-049b S4b; REQ-AST-051-053). No I/O."""

import io
import zipfile
from collections.abc import Sequence
from datetime import UTC, date, datetime

import pytest

from app.modules.assets.domain.batch import (
    MAX_IMPORT_ROWS,
    NO_KEY_COLUMN,
    UNKNOWN_COLUMN,
    AssetBulkAction,
    ImportKind,
    ImportMatch,
    ImportRefused,
    MergeCandidate,
    MergeSide,
    bulk_change_problems,
    day,
    default_side,
    merge_choice_problems,
    read_import,
    suggest_survivor,
)
from app.modules.assets.domain.catalogue import Problem
from app.shared import sheets


def _codes(problems: Sequence[Problem]) -> set[tuple[str, str]]:
    return {(p.field, p.code) for p in problems}


def test_bulk_changes_are_checked_per_action() -> None:
    assert bulk_change_problems(AssetBulkAction.EDIT, {"location": "A"}) == []
    assert _codes(bulk_change_problems(AssetBulkAction.EDIT, {})) == {("changes", "required")}
    # Money and identifiers are never set in bulk (D-157; unique values).
    assert _codes(bulk_change_problems(AssetBulkAction.EDIT, {"purchase_price": 1})) == {
        ("changes.purchase_price", "invalid_choice")
    }
    assert _codes(bulk_change_problems(AssetBulkAction.EDIT, {"tag": "X"})) == {
        ("changes.tag", "invalid_choice")
    }
    assert _codes(bulk_change_problems(AssetBulkAction.MOVE, {})) == {
        ("changes.to_state_id", "required")
    }
    assert bulk_change_problems(AssetBulkAction.ASSIGN, {}) == []  # back to no one
    assert _codes(bulk_change_problems(AssetBulkAction.ASSIGN, {"holder_kind": "user"})) == {
        ("changes.holder_id", "required")
    }
    assert _codes(
        bulk_change_problems(AssetBulkAction.ASSIGN, {"holder_kind": "asset", "holder_id": "x"})
    ) == {("changes.holder_kind", "invalid_choice")}
    assert _codes(bulk_change_problems(AssetBulkAction.DELETE, {"location": "A"})) == {
        ("changes.location", "invalid_choice")
    }


def test_the_discovered_asset_then_the_newest_scan_is_suggested_to_survive() -> None:
    by_hand = MergeCandidate(discovered=False, last_scanned_at=None)
    old = MergeCandidate(discovered=True, last_scanned_at=datetime(2026, 1, 1, tzinfo=UTC))
    new = MergeCandidate(discovered=True, last_scanned_at=datetime(2026, 6, 1, tzinfo=UTC))
    assert suggest_survivor(by_hand, old) == 1
    assert suggest_survivor(old, by_hand) == 0
    assert suggest_survivor(old, new) == 1
    assert suggest_survivor(new, old) == 0
    assert suggest_survivor(by_hand, by_hand) == 0  # as asked


def test_a_field_keeps_the_survivors_value_unless_it_has_none() -> None:
    assert default_side("A", "B") == MergeSide.SURVIVOR
    assert default_side(None, "B") == MergeSide.MERGED
    assert default_side("", "B") == MergeSide.MERGED
    assert default_side(None, None) == MergeSide.SURVIVOR


def test_merge_choices_are_checked_and_money_needs_the_right() -> None:
    assert merge_choice_problems({"name": "merged"}, sees_money=False) == []
    assert _codes(merge_choice_problems({"tag": "merged"}, sees_money=True)) == {
        ("choices.tag", "invalid_choice")
    }
    assert _codes(merge_choice_problems({"name": "both"}, sees_money=True)) == {
        ("choices.name", "invalid_choice")
    }
    assert _codes(merge_choice_problems({"purchase_price": "merged"}, sees_money=False)) == {
        ("choices.purchase_price", "permission_denied")
    }
    assert merge_choice_problems({"purchase_price": "merged"}, sees_money=True) == []


def _read(content: bytes, *, kind: ImportKind = ImportKind.ASSETS, name: str = "a.csv") -> None:
    match = ImportMatch.SERIAL_NUMBER if kind == ImportKind.ASSETS else ImportMatch.NAME
    read_import(kind, match, sheets.file_format(name, content), content)


def test_import_headings_map_to_fields_and_unknown_or_missing_keys_refuse() -> None:
    found = read_import(
        ImportKind.ASSETS,
        ImportMatch.SERIAL_NUMBER,
        "csv",
        b"Name,Serial Number,serial_number,Cost center\nA,S-1,,CC\n\n",
    )
    assert found.fields == ["name", "serial_number", "serial_number", "cost_centre"]
    assert found.rows == [(2, {"name": "A", "serial_number": "", "cost_centre": "CC"})]
    with pytest.raises(ImportRefused) as unknown:
        _read(b"Serial number,Colour\nS-1,red\n")
    assert (unknown.value.code, unknown.value.detail) == (UNKNOWN_COLUMN, "Colour")
    with pytest.raises(ImportRefused) as no_key:
        _read(b"Name\nA\n")
    assert (no_key.value.code, no_key.value.detail) == (NO_KEY_COLUMN, "serial_number")
    with pytest.raises(ImportRefused) as vendor_key:
        _read(b"Email\na@b.c\n", kind=ImportKind.VENDORS)
    assert vendor_key.value.code == NO_KEY_COLUMN


def test_twenty_thousand_rows_are_read_and_one_more_is_refused() -> None:
    rows = b"".join(b"S-%d\n" % n for n in range(MAX_IMPORT_ROWS))
    found = read_import(ImportKind.ASSETS, ImportMatch.SERIAL_NUMBER, "csv", b"Serial\n" + rows)
    assert len(found.rows) == MAX_IMPORT_ROWS
    with pytest.raises(ImportRefused) as over:
        read_import(
            ImportKind.ASSETS, ImportMatch.SERIAL_NUMBER, "csv", b"Serial\n" + rows + b"S-x\n"
        )
    assert over.value.code == sheets.TOO_MANY_ROWS


def test_wp021_limits_hold_for_imports() -> None:
    assert sheets.MAX_FILE_BYTES == 5 * 1024 * 1024
    assert (sheets.MAX_COLUMNS, sheets.MAX_CELL_CHARS) == (40, 5000)
    with pytest.raises(ImportRefused) as wide:
        _read((",".join(["Name"] * 41) + "\n").encode())
    assert wide.value.code == sheets.TOO_MANY_COLUMNS
    with pytest.raises(ImportRefused) as long_cell:
        _read(b"Serial\n" + b"x" * 5001 + b"\n")
    assert (long_cell.value.code, long_cell.value.detail) == (sheets.CELL_TOO_LONG, "2")
    with pytest.raises(ImportRefused) as large:
        _read(b"Serial\n" + b"x" * sheets.MAX_FILE_BYTES)
    assert large.value.code == sheets.FILE_TOO_LARGE


def test_a_zip_bomb_or_a_broken_workbook_is_refused_before_openpyxl_reads_it() -> None:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", "0" * 5_000_000)
    with pytest.raises(ImportRefused) as bomb:
        read_import(ImportKind.ASSETS, ImportMatch.TAG, "xlsx", out.getvalue())
    assert bomb.value.code == sheets.FILE_UNSAFE
    with pytest.raises(ImportRefused) as broken:
        read_import(ImportKind.ASSETS, ImportMatch.TAG, "xlsx", b"PK\x03\x04 nonsense")
    assert broken.value.code == sheets.FILE_NOT_READABLE
    with pytest.raises(sheets.SheetRefused):
        sheets.file_format("assets.xlsx", b"plain text")  # an "xlsx" that is no zip


def test_dates_read_iso_and_excels_datetimes() -> None:
    assert day("2026-11-11") == date(2026, 11, 11)
    assert day("2026-11-11 00:00:00") == date(2026, 11, 11)
    assert day("11/11/2026") is None
    assert day("") is None
