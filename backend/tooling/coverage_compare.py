"""Coverage of a partial PR run's changed files against the nightly's (CI test selection).

A PR run that selected only some test files (tooling/test_select.py) cannot hold the combined
90% (pyproject.toml): most of the code is not exercised by its tests at all. It checks the code
it changed instead: each changed app .py file's line coverage may fall at most TOLERANCE
percentage points below the newest nightly's (the `backend-coverage-baseline` artifact, a
`coverage json` of the full suite), and a file the nightly does not know (a new file) must
reach NEW_FILE_MINIMUM. Without a baseline it passes with a notice: the merge queue runs the
full suite and enforces the combined 90% on every merge.

ADVISORY ONLY (2026-11-12, lane C on #445): a drop is a warning, never a failure. The nightly's
coverage includes tests that reach a file only over HTTP through `create_app`, which
test_select deliberately does not pick (its docstring), so a PR touching only a router showed
a false drop (automation/api/workflows.py, 91.8% against 97.1%). Telling those lines apart needs
per-test coverage, which CI does not keep. The merge queue's full run still enforces the
combined 90% on every merge, so a real loss cannot land.

CLI (from backend/): `uv run python -m tooling.coverage_compare --selection selection.json
--current coverage.json [--baseline coverage-baseline.json]`. Never imported by the app.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

TOLERANCE = 1.0  # percentage points below the nightly
NEW_FILE_MINIMUM = 90.0  # pyproject.toml's fail_under, for a file the nightly never measured
ROOTS = {"app", "tooling", "workers"}


def _key(path: str) -> str:
    """A measured file's path relative to backend/, whether coverage stored it absolute or not."""
    posix = PurePosixPath(path.replace("\\", "/"))
    parts = posix.parts
    for index, part in enumerate(parts[:-1]):
        if part == "backend" and parts[index + 1] in ROOTS:
            return "/".join(parts[index + 1 :])
    return str(posix)


def line_coverage(report: dict[str, Any]) -> dict[str, float]:
    """Each measured file's line coverage in percent, from a `coverage json` report."""
    found: dict[str, float] = {}
    for path, data in report.get("files", {}).items():
        summary = data["summary"]
        statements = summary["num_statements"]
        covered = summary["covered_lines"]
        found[_key(path)] = 100.0 if statements == 0 else 100.0 * covered / statements
    return found


@dataclass(frozen=True)
class Verdict:
    """One changed file's coverage now and in the nightly, and whether it holds."""

    path: str
    current: float | None
    baseline: float | None
    ok: bool
    note: str


def compare(
    changed: list[str], current: dict[str, float], baseline: dict[str, float]
) -> list[Verdict]:
    """One verdict per changed file; a file coverage does not measure (no statements) passes."""
    verdicts: list[Verdict] = []
    for path in sorted(set(changed)):
        now = current.get(path)
        before = baseline.get(path)
        if now is None:
            verdicts.append(Verdict(path, None, before, ok=True, note="not measured"))
        elif before is None:
            ok = now >= NEW_FILE_MINIMUM
            verdicts.append(
                Verdict(path, now, None, ok=ok, note=f"new file, needs {NEW_FILE_MINIMUM:.0f}%")
            )
        else:
            ok = now >= before - TOLERANCE
            verdicts.append(Verdict(path, now, before, ok=ok, note=f"nightly {before:.1f}%"))
    return verdicts


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}%"


def main(argv: list[str] | None = None) -> int:
    """Compare and print a line per changed file; warnings only, always 0 (advisory)."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--selection", type=Path, required=True, help="tooling.test_select's")
    parser.add_argument("--current", type=Path, required=True, help="this run's coverage json")
    parser.add_argument("--baseline", type=Path, help="the nightly's coverage json")
    args = parser.parse_args(argv)
    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    changed = [str(p) for p in selection.get("app_files", [])]
    if args.baseline is None or not args.baseline.is_file():
        _say(
            "::notice title=coverage::No nightly coverage baseline: the changed files are not "
            "compared (the merge queue checks the full 90%)"
        )
        return 0
    current = line_coverage(json.loads(args.current.read_text(encoding="utf-8")))
    baseline = line_coverage(json.loads(args.baseline.read_text(encoding="utf-8")))
    verdicts = compare(changed, current, baseline)
    for v in verdicts:
        mark = "ok  " if v.ok else "LOW "
        _say(f"{mark} {v.path}: {_pct(v.current)} ({v.note})")
    failed = [v for v in verdicts if not v.ok]
    if failed:
        _say(
            f"::warning title=coverage (advisory)::{len(failed)} changed file(s) below the "
            "nightly on the selected tests only (tests that reach them over HTTP may not have "
            "run; the merge queue checks the full 90%): " + ", ".join(v.path for v in failed)
        )
        return 0
    _say(f"Coverage of {len(verdicts)} changed app file(s) holds against the nightly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
