"""Every workflow problem code has a label in English, Arabic and Urdu (CLAUDE.md rule d).

The designer shows a definition's problems on the canvas (REQ-WF-019); a code without a label
would surface as raw text. Codes are read from the workflow domain and its admin service, as
`(code, {params})` and `(where, code, {params})` tuples; the shared conditions grammar's codes
(unknown_operator ...) keep their `errors.field.<code>` labels.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    ROOT / "app/modules/automation/domain/workflows.py",
    ROOT / "app/modules/automation/service/workflow_admin.py",
)
RESOURCES = ROOT.parent / "frontend/packages/labels/src/resources"
# A code is a string followed by its params dict; `.get("config", {})` is a default, not a code.
_CODE = re.compile(r'(?<!get\()"([a-z][a-z0-9_]+)",\s*\{')
_RETURNED = re.compile(r'if ok else "([a-z][a-z0-9_]+)"')  # variable_value_problem
_KEY = re.compile(r"^\s*'([^']+)':", re.MULTILINE)


def workflow_problem_codes() -> set[str]:
    codes: set[str] = set()
    for source in SOURCES:
        text = source.read_text(encoding="utf-8")
        codes |= set(_CODE.findall(text)) | set(_RETURNED.findall(text))
    return codes


def _keys(language: str) -> set[str]:
    found: set[str] = set()
    for resource in RESOURCES.glob(f"*/{language}.ts"):
        found |= set(_KEY.findall(resource.read_text(encoding="utf-8")))
    return found


def test_the_scan_finds_the_codes() -> None:
    codes = workflow_problem_codes()
    assert {"output_not_linked", "sub_flow_recursion", "variable_value_invalid"} <= codes
    assert "config" not in codes


@pytest.mark.parametrize("language", ["en", "ar", "ur"])
def test_every_workflow_problem_code_has_a_label(language: str) -> None:
    keys = _keys(language)
    missing = sorted(
        code
        for code in workflow_problem_codes()
        if f"workflow_problem.{code}" not in keys and f"errors.field.{code}" not in keys
    )
    assert missing == [], f"add workflow_problem.<code> labels in {language}"
