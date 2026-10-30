"""The required checks report on every pull request and in the merge queue.

A required check that never reports blocks a merge forever: a path-filtered workflow did that to
docs-only PRs (#112), and a workflow without the `merge_group` trigger would do it to every PR in
the merge queue. Heavy jobs decide inside, with their first step (`.github/actions/changes`).
The names are the required status checks on `main` (the ruleset); keep both lists equal.

Read line by line (no YAML library is a declared dependency): the workflows keep the layout this
relies on, two-space indents with `on:` and `jobs:` at the top level.
"""

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
REQUIRED = {
    "backend",
    "frontend",
    "pre-commit",
    "chart",
    "core profile, integration and e2e",
    "dependency audit (pip-audit, pnpm audit)",
    "filesystem scan (Trivy)",
    "secret scan (gitleaks)",
}
FILTERS = ("paths:", "paths-ignore:", "branches:", "branches-ignore:")


def _block(lines: list[str], key: str) -> list[str]:
    """The lines of a top-level mapping (`on:`, `jobs:`), without comments."""
    start = lines.index(f"{key}:") + 1
    found = []
    for line in lines[start:]:
        if line and not line.startswith((" ", "#")):
            break
        if line.strip() and not line.lstrip().startswith("#"):
            found.append(line)
    return found


def _triggers(lines: list[str]) -> dict[str, list[str]]:
    """Each trigger with its settings lines."""
    triggers: dict[str, list[str]] = {}
    current = ""
    for line in _block(lines, "on"):
        if re.match(r"^  [a-z_]+:", line):
            current = line.strip().split(":")[0]
            triggers[current] = []
        elif current:
            triggers[current].append(line.strip())
    return triggers


def _job_names(lines: list[str]) -> set[str]:
    return {
        line.split("name:", 1)[1].strip().strip('"')
        for line in _block(lines, "jobs")
        if re.match(r"^    name: ", line)
    }


def _required() -> dict[str, tuple[str, dict[str, list[str]]]]:
    found: dict[str, tuple[str, dict[str, list[str]]]] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for name in _job_names(lines) & REQUIRED:
            found[name] = (path.name, _triggers(lines))
    return found


def test_every_required_check_has_a_job() -> None:
    assert set(_required()) == REQUIRED


def test_required_checks_run_on_every_pr_and_in_the_merge_queue() -> None:
    for name, (workflow, triggers) in _required().items():
        for event in ("pull_request", "merge_group"):
            assert event in triggers, f"{workflow} ({name}) must trigger on {event}"
            filtered = [s for s in triggers[event] if s.startswith(FILTERS)]
            assert not filtered, f"{workflow} ({name}): no {filtered} on {event}"
