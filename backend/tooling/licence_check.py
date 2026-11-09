"""`make licence-check`: the shipped JavaScript dependencies' licences against the allow-list.

CLAUDE.md §3: every dependency must allow on-prem redistribution, and AGPL or source-available
needs explicit approval (ADR-012). Vulnerability audits run in CI; this is the licence gate
(Haider, 2026-11-06). It reads `pnpm licenses list --prod --json` for a pnpm project (the
frontend workspace, the mobile app) and fails on any licence outside the allow-list, unknown
ones included.

SPDX expressions are understood: `(MIT OR Apache-2.0)` passes if either does, `MIT AND CC-BY-4.0`
only if both do. A package whose licence is acceptable but not recognised in the report goes in
EXCEPTIONS by name with the reason, never by widening the list.

    uv run python -m tooling.licence_check ../frontend [../mobile]
"""

import json
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ALLOWED = frozenset(
    {
        "MIT",
        "MIT-0",
        "ISC",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "0BSD",
        "BlueOak-1.0.0",
        "CC0-1.0",
        "Unlicense",
        "Zlib",
        "Python-2.0",
        "MPL-2.0",  # file-level copyleft: fine for unmodified use (Haider, 2026-11-06)
        "OFL-1.1",  # the bundled fonts (D-137)
        "CC-BY-4.0",  # data only (e.g. caniuse-lite), attributed in the notices
    }
)
# Packages whose reported licence string is unusual but checked by hand: name -> reason.
EXCEPTIONS: Mapping[str, str] = {}

_TOKEN = re.compile(r"\(|\)|\bAND\b|\bOR\b|\bWITH\b|[A-Za-z0-9.+-]+")


@dataclass(frozen=True, slots=True)
class Refusal:
    """A package whose licence is not on the allow-list."""

    project: str
    name: str
    versions: tuple[str, ...]
    licence: str


def _expression_ok(expression: str) -> bool:
    """Whether an SPDX expression is satisfied by the allow-list (OR: any side, AND: both)."""
    tokens = [t for t in _TOKEN.findall(expression) if t != "WITH"]
    position = 0

    def term() -> bool:
        nonlocal position
        if position >= len(tokens):
            return False
        word = tokens[position]
        position += 1
        if word == "(":
            value = either()
            if position < len(tokens) and tokens[position] == ")":
                position += 1
            return value
        return word.removesuffix("+") in ALLOWED

    def both() -> bool:
        nonlocal position
        value = term()
        while position < len(tokens) and tokens[position] == "AND":
            position += 1
            value = term() and value
        return value

    def either() -> bool:
        nonlocal position
        value = both()
        while position < len(tokens) and tokens[position] == "OR":
            position += 1
            value = both() or value
        return value

    return either() and position == len(tokens)


def refusals(project: str, report: Mapping[str, Iterable[Mapping[str, Any]]]) -> list[Refusal]:
    """Every package in a `pnpm licenses list --json` report whose licence is not allowed."""
    found: list[Refusal] = []
    for licence, packages in report.items():
        for package in packages:
            name = str(package.get("name", "?"))
            if name in EXCEPTIONS or _expression_ok(str(package.get("license") or licence)):
                continue
            found.append(
                Refusal(project, name, tuple(map(str, package.get("versions", ()))), licence)
            )
    return found


def report_for(project: Path) -> dict[str, Any]:
    """Pnpm's production licence report for a project (recursive in a workspace)."""
    done = subprocess.run(
        ["pnpm", "-r", "licenses", "list", "--prod", "--json"],  # noqa: S607
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    )
    parsed: dict[str, Any] = json.loads(done.stdout or "{}")
    return parsed


def main(argv: Sequence[str]) -> int:  # pragma: no cover - thin CLI over `refusals`
    """Check each project given; a missing one (the mobile app before it lands) is skipped."""
    bad: list[Refusal] = []
    for raw in argv:
        project = Path(raw)
        if not (project / "package.json").is_file():
            sys.stdout.write(f"{project}: no package.json, skipped\n")
            continue
        found = refusals(project.name, report_for(project))
        bad += found
        sys.stdout.write(f"{project}: {'ok' if not found else f'{len(found)} refused'}\n")
    for refusal in bad:
        versions = ", ".join(refusal.versions)
        sys.stdout.write(f"  {refusal.project}: {refusal.name} {versions}: {refusal.licence}\n")
    if bad:
        sys.stdout.write(
            "Not on the allow-list (CLAUDE.md §3, ADR-012): ask before adding these.\n"
        )
    return 1 if bad else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main(sys.argv[1:]))
