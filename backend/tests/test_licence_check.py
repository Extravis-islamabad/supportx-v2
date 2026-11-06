"""The licence gate (tooling/licence_check.py): the allow-list and SPDX expressions."""

import pytest

from tooling.licence_check import _expression_ok, refusals


@pytest.mark.parametrize(
    ("expression", "ok"),
    [
        ("MIT", True),
        ("Apache-2.0", True),
        ("(MIT OR Apache-2.0)", True),
        ("(GPL-3.0-only OR MIT)", True),
        ("MIT AND CC-BY-4.0", True),
        ("MIT AND GPL-2.0-only", False),
        ("GPL-3.0-only", False),
        ("AGPL-3.0-or-later", False),
        ("SSPL-1.0", False),
        ("BUSL-1.1", False),
        ("UNLICENSED", False),
        ("Unknown", False),
        ("Apache-2.0 WITH LLVM-exception", False),
        ("", False),
    ],
)
def test_expressions(expression: str, *, ok: bool) -> None:
    assert _expression_ok(expression) is ok


def test_a_report_lists_only_what_is_not_allowed() -> None:
    report = {
        "MIT": [{"name": "react", "versions": ["18.3.1"], "license": "MIT"}],
        "GPL-3.0": [{"name": "some-gpl", "versions": ["1.0.0"], "license": "GPL-3.0"}],
        "Unknown": [{"name": "mystery", "versions": ["0.1.0"]}],
    }
    found = refusals("frontend", report)
    assert sorted(r.name for r in found) == ["mystery", "some-gpl"]
