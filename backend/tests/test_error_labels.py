"""Every error code the API can return has an English and an Arabic label (CLAUDE.md rule d).

The UI shows `message_key` through the labels package; a code without a label would surface as
humanized raw text. Reads the TypeScript resources directly so the check runs in the backend job.
"""

import importlib
import pkgutil
import re
import typing
from pathlib import Path

import pytest

from app.core import errors
from app.shared.api.filters import FIELD_ERROR_CODES

RESOURCES = Path(__file__).resolve().parents[2] / "frontend/packages/labels/src/resources"
_KEY = re.compile(r"^\s*'([^']+)':", re.MULTILINE)


APP_DIR = Path(__file__).resolve().parents[1] / "app"
# Per-raise codes, e.g. `NotFound(code="tenant_not_found")`, anywhere in the application code.
_RAISE_CODE = re.compile(r"\bcode=\"([a-z][a-z0-9_]*)\"")
# ... and problem codes passed by keyword, e.g. `_invalid(..., problem="invalid_sort")`.
_PROBLEM_CODE = re.compile(r"\bproblem=\"([a-z][a-z0-9_]*)\"")
# Field-level codes (`FieldError(..., code="read_only")`) are labelled as errors.field.<code>.
_FIELD_ERROR = re.compile(
    r"FieldError\((?:[^()]|\([^()]*\))*?\bcode=\"([a-z][a-z0-9_]*)\"", re.DOTALL
)


def _import_application() -> None:
    """Import every application module, so every error class is known.

    Error classes are found as subclasses, which exist only once their module is imported: with
    pytest-xdist a worker may not have imported, say, the mail service before this test runs.
    """
    for module in pkgutil.walk_packages([str(APP_DIR)], prefix="app."):
        if ".tests" not in module.name:
            importlib.import_module(module.name)


def error_codes() -> set[str]:
    _import_application()
    codes = {cls.code for cls in _subclasses(errors.AppError)} | {errors.AppError.code}
    codes |= set(errors._HTTP_STATUS_CODES.values())  # noqa: SLF001 - the mapping is the contract
    for source in APP_DIR.rglob("*.py"):
        if "tests" not in source.parts:
            text = source.read_text(encoding="utf-8")
            field_only = set(_FIELD_ERROR.findall(text))
            codes |= (set(_RAISE_CODE.findall(text)) - field_only) | set(
                _PROBLEM_CODE.findall(text)
            )
    return codes


# Modules that build field errors from (field, code) pairs list their codes in a FIELD_PROBLEMS set.
_PROBLEM_SET = re.compile(
    r"^FIELD_PROBLEMS = frozenset\(\s*\{(.*?)\}\s*\)", re.DOTALL | re.MULTILINE
)
_QUOTED = re.compile(r"\"([a-z][a-z0-9_]*)\"")


def field_error_codes() -> set[str]:
    codes = set(FIELD_ERROR_CODES)
    for source in APP_DIR.rglob("*.py"):
        for block in _PROBLEM_SET.findall(source.read_text(encoding="utf-8")):
            codes |= set(_QUOTED.findall(block))
        if "tests" not in source.parts:
            codes |= set(_FIELD_ERROR.findall(source.read_text(encoding="utf-8")))
    return codes


def test_per_raise_codes_are_collected() -> None:
    assert {"csrf_failed", "version_conflict", "tenant_not_found"} <= error_codes()


def _subclasses(cls: type[errors.AppError]) -> list[type[errors.AppError]]:
    found = cls.__subclasses__()
    return found + [sub for child in found for sub in _subclasses(child)]


def label_text(locale: str) -> str:
    """A language's label sources: each module keeps them in `<module>/<locale>.ts` (D-127)."""
    files = [RESOURCES / f"{locale}.ts", *sorted(RESOURCES.glob(f"*/{locale}.ts"))]
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


def label_keys(locale: str) -> set[str]:
    """Every key of a language."""
    return set(_KEY.findall(label_text(locale)))


@pytest.mark.parametrize("locale", ["en", "ar"])
def test_every_error_code_has_a_label(locale: str) -> None:
    missing = sorted(
        errors.message_key_for(code)
        for code in error_codes()
        if errors.message_key_for(code) not in label_keys(locale)
    )
    assert missing == [], f"add these keys to packages/labels/src/resources/{locale}.ts"


@pytest.mark.parametrize("locale", ["en", "ar"])
def test_every_field_error_code_has_a_label(locale: str) -> None:
    """Field errors (filter DSL, list parameters, body checks) point at `errors.field.<code>`."""
    missing = sorted(
        f"errors.field.{code}"
        for code in field_error_codes()
        if f"errors.field.{code}" not in label_keys(locale)
    )
    assert missing == [], f"add these keys to packages/labels/src/resources/{locale}.ts"


def _every_pydantic_error_type() -> list[str]:
    from pydantic_core.core_schema import ErrorType  # noqa: PLC0415 - only this test needs it

    return sorted(typing.get_args(ErrorType))


@pytest.mark.parametrize("locale", ["en", "ar", "ur"])
def test_qa6_aut_01_02_no_pydantic_code_reaches_a_person(locale: str) -> None:
    """QA6-AUT-01/02: "Uuid Parsing", "Date From Datetime Parsing" showed as raw codes.

    Every Pydantic error type, empty or not, becomes one of the app's labelled field codes.
    """
    keys = label_keys(locale)
    wrong = []
    for kind in _every_pydantic_error_type():
        for given in ("", "x", None):
            found = errors._field_error({"type": kind, "loc": ("body", "f"), "input": given})  # noqa: SLF001 - the mapping is the contract
            own = kind == "invalid_key"  # also the app's own code, labelled; passes through
            if (
                found.code not in errors.VALIDATION_CODES and not own
            ) or found.message_key not in keys:
                wrong.append((kind, given, found.code))
    assert wrong == []


def test_qa6_aut_01_02_plain_codes_for_the_reported_cases() -> None:
    def code(kind: str, given: object = "x") -> str:
        return errors._field_error({"type": kind, "loc": ("body", "f"), "input": given}).code  # noqa: SLF001 - the mapping is the contract

    assert code("uuid_parsing") == "invalid_value"
    assert code("uuid_parsing", "") == "required"
    assert code("date_from_datetime_parsing") == "invalid_date"
    assert code("date_from_datetime_parsing", "") == "required"
    assert code("int_parsing") == "invalid_number"
    assert code("literal_error") == "invalid_choice"
    assert code("extra_forbidden") == "invalid_value"
