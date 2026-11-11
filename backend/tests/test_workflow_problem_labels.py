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


# Why a run stopped (REQ-WF-024): the interpreter's own codes, the owning modules' command
# errors and a webhook's egress refusals (webhook_<code>). The record's Workflows panel shows
# workflow_failure.<code> (or the shared errors./workflow_problem. label), never the code.
RUN_TIME_CODES = (
    "record_canceled",
    "command_failed",
    "output_not_linked",
    "step_limit",
    "loop_limit",
    "join_without_split",
    "not_found",
    "command_not_supported",
    "approval_invalid",
    "approval_not_offered",
    "notify_not_offered",
    "tasks_invalid",
    "task_canceled",
    "sub_flow_failed",
    "function_not_offered",
    "workflow_identity_missing",
)


def _egress_codes() -> set[str]:
    from app.shared.egress import client  # noqa: PLC0415 - the module's constants, read here

    names = ("BLOCKED", "UNREACHABLE", "TIMEOUT", "TOO_LARGE", "INSECURE", "TLS", "REDIRECT")
    return {str(getattr(client, n)) for n in (*names, "HTTP_STATUS", "INVALID")}


@pytest.mark.parametrize("language", ["en", "ar", "ur"])
def test_every_run_time_failure_has_a_label(language: str) -> None:
    keys = _keys(language)
    codes = {*RUN_TIME_CODES, *(f"webhook_{c}" for c in _egress_codes())}
    missing = sorted(
        c
        for c in codes
        if not {f"workflow_failure.{c}", f"errors.{c}", f"workflow_problem.{c}"} & keys
    )
    assert missing == [], f"add workflow_failure.<code> labels in {language}"
