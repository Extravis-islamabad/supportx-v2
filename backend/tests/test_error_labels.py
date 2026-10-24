"""Every error code the API can return has an English and an Arabic label (CLAUDE.md rule d).

The UI shows `message_key` through the labels package; a code without a label would surface as
humanized raw text. Reads the TypeScript resources directly so the check runs in the backend job.
"""

import re
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


def error_codes() -> set[str]:
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


def label_keys(locale: str) -> set[str]:
    return set(_KEY.findall((RESOURCES / f"{locale}.ts").read_text(encoding="utf-8")))


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
