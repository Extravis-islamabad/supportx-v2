"""A PR run that selected tests checks its changed files' coverage against the nightly's."""

import json
from pathlib import Path
from typing import Any

import pytest

from tooling import coverage_compare
from tooling.coverage_compare import compare, line_coverage


def _report(files: dict[str, tuple[int, int]]) -> dict[str, Any]:
    """A `coverage json` report: path -> (covered lines, statements)."""
    return {
        "files": {
            path: {"summary": {"covered_lines": covered, "num_statements": statements}}
            for path, (covered, statements) in files.items()
        }
    }


def test_paths_are_read_relative_to_backend_whether_absolute_or_not() -> None:
    found = line_coverage(
        _report(
            {
                "/home/runner/work/supportx-v2/supportx-v2/backend/app/modules/a/x.py": (9, 10),
                "app/modules/a/y.py": (1, 4),
                "/elsewhere/app/z.py": (0, 0),
            }
        )
    )
    assert found == {
        "app/modules/a/x.py": 90.0,
        "app/modules/a/y.py": 25.0,
        "/elsewhere/app/z.py": 100.0,
    }


def test_a_changed_file_may_lose_at_most_one_point() -> None:
    baseline = {"app/a.py": 95.0, "app/b.py": 95.0}
    current = {"app/a.py": 94.0, "app/b.py": 93.9}
    verdicts = {v.path: v.ok for v in compare(["app/a.py", "app/b.py"], current, baseline)}
    assert verdicts == {"app/a.py": True, "app/b.py": False}


def test_a_new_file_needs_ninety_percent_and_an_unmeasured_one_passes() -> None:
    verdicts = compare(
        ["app/new.py", "app/thin.py", "app/gone.py"], {"app/new.py": 90.0, "app/thin.py": 89.9}, {}
    )
    assert [(v.path, v.ok) for v in verdicts] == [
        ("app/gone.py", True),
        ("app/new.py", True),
        ("app/thin.py", False),
    ]


def _files(tmp_path: Path, current: dict[str, Any], baseline: dict[str, Any] | None) -> list[str]:
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"all": False, "files": [], "app_files": ["app/a.py"]}))
    now = tmp_path / "current.json"
    now.write_text(json.dumps(current))
    args = ["--selection", str(selection), "--current", str(now)]
    if baseline is not None:
        before = tmp_path / "baseline.json"
        before.write_text(json.dumps(baseline))
        args += ["--baseline", str(before)]
    return args


def test_the_cli_fails_on_lost_coverage_and_passes_without_a_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lost = _files(tmp_path, _report({"app/a.py": (8, 10)}), _report({"app/a.py": (10, 10)}))
    assert coverage_compare.main(lost) == 1
    assert (
        "::error title=coverage::1 changed file(s) lost coverage: app/a.py"
        in capsys.readouterr().out
    )
    held = _files(tmp_path, _report({"app/a.py": (10, 10)}), _report({"app/a.py": (10, 10)}))
    assert coverage_compare.main(held) == 0
    assert "holds against the nightly" in capsys.readouterr().out
    none = _files(tmp_path, _report({"app/a.py": (0, 10)}), None)
    assert coverage_compare.main([*none, "--baseline", str(tmp_path / "missing.json")]) == 0
    assert "No nightly coverage baseline" in capsys.readouterr().out
