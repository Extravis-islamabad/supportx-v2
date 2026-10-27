"""The person record's rules and the people file reader, without a database (WP-021)."""

import io
import zipfile

import pytest
from openpyxl import Workbook

from app.modules.identity_access.domain.people import full_name, person_problems
from app.modules.identity_access.domain.people_import import (
    MAX_COLUMNS,
    MAX_ROWS,
    ImportFailure,
    ImportRefused,
    check_zip,
    file_format,
    flag,
    read_rows,
)


def test_full_name() -> None:
    assert full_name("Amal", "Saleh") == "Amal Saleh"
    assert full_name("Amal", None) == "Amal"


def test_person_problems_name_each_field_with_its_limit() -> None:
    problems = person_problems(
        {
            "first_name": None,
            "email": "not-an-email",
            "phone": "call me",
            "job_title": "x" * 201,
            "locale": "fr",
            "time_zone": "Mars/Base",
            "request_visibility": "everything",
        }
    )
    assert sorted(problems, key=str) == sorted(
        [
            ("first_name", "required", {}),
            ("email", "email_not_valid", {}),
            ("phone", "phone_not_valid", {}),
            ("job_title", "value_too_long", {"max_length": 200}),
            ("locale", "invalid_choice", {}),
            ("time_zone", "unknown_time_zone", {}),
            ("request_visibility", "invalid_choice", {}),
        ],
        key=str,
    )


def test_only_sent_fields_are_checked() -> None:
    assert person_problems({"last_name": "Saleh"}) == []


def test_file_format_is_checked_by_content_and_extension() -> None:
    assert file_format("people.csv", b"First name\n") == "csv"
    assert file_format("people.xlsx", b"PK\x03\x04rest") == "xlsx"
    for name, content in (
        ("people.xlsx", b"First name"),
        ("people.csv", b"PK\x03\x04"),
        ("people.pdf", b"%PDF"),
    ):
        with pytest.raises(ImportRefused) as refused:
            file_format(name, content)
        assert refused.value.failure is ImportFailure.NOT_READABLE


def test_csv_headings_map_to_fields_and_blank_rows_are_skipped() -> None:
    sheet = read_rows(
        "csv",
        "﻿First Name;E-mail address;employee_id\nAmal;a@x.test;7\n;;\n".replace(
            "E-mail address", "Email address"
        ).encode(),
    )
    assert sheet.fields == ["first_name", "email", "employee_id"]
    assert sheet.rows == [(2, {"first_name": "Amal", "email": "a@x.test", "employee_id": "7"})]


@pytest.mark.parametrize(
    ("content", "failure"),
    [
        (b"", ImportFailure.NO_HEADER),
        (b"First name\n", ImportFailure.EMPTY),
        (b"Email\nx@y.test\n", ImportFailure.NO_NAME_COLUMN),
        (b"First name,Shoe size\nA,40\n", ImportFailure.UNKNOWN_COLUMN),
        ("First name\n".encode("utf-16"), ImportFailure.NOT_UTF8),
        (("First name\n" + "A\n" * (MAX_ROWS + 1)).encode(), ImportFailure.TOO_MANY_ROWS),
        (
            (",".join(["First name"] * (MAX_COLUMNS + 1)) + "\n").encode(),
            ImportFailure.TOO_MANY_COLUMNS,
        ),
        (("First name\n" + "A" * 5001 + "\n").encode(), ImportFailure.CELL_TOO_LONG),
    ],
)
def test_csv_refusals(content: bytes, failure: ImportFailure) -> None:
    with pytest.raises(ImportRefused) as refused:
        read_rows("csv", content)
    assert refused.value.failure is failure


def test_xlsx_rows_with_numbers_kept_as_written() -> None:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(["First name", "Phone", "VIP"])
    sheet.append(["Amal", 966500000001, "yes"])
    sheet.append(["=1+1", None, None])  # a formula is never evaluated: no saved value, no row
    buffer = io.BytesIO()
    book.save(buffer)
    rows = read_rows("xlsx", buffer.getvalue()).rows
    assert rows == [(2, {"first_name": "Amal", "phone": "966500000001", "vip": "yes"})]


def test_a_zip_bomb_is_refused_before_it_is_opened() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"0" * (20 * 1024 * 1024))
    with pytest.raises(ImportRefused) as refused:
        check_zip(buffer.getvalue())
    assert refused.value.failure is ImportFailure.UNSAFE


def test_flags() -> None:
    assert [flag(v) for v in ("Yes", "x", "0", "", "maybe")] == [True, True, False, False, None]
