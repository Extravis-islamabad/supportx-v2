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


# --- Heavy jobs run in the merge queue, not on every PR (product owner, 2026-11-02) ------------

# Jobs too slow for every push to a PR. On a PR they report success at once from their first
# step (`queue-only`); the merge queue runs them on the exact merge commit before it lands.
HEAVY = {
    "core profile, integration and e2e",
    "images (build, Trivy, SBOM)",
    "k3d install and smoke test",
    "pdf (worker image)",
    "chart",
    "filesystem scan (Trivy)",
    "worker resilience",
}
# Workflows whose checks gate main: the queue tested the merge commit, so no push run on main.
GATING = ("ci.yml", "security.yml", "stack-smoke.yml", "cluster.yml")


def _jobs(lines: list[str]) -> dict[str, list[str]]:
    """Each job's lines by its display name (the status check's name)."""
    jobs: dict[str, list[str]] = {}
    current: list[str] = []
    for line in _block(lines, "jobs"):
        if re.match(r"^  [a-z0-9_-]+:$", line):
            current = []
        current.append(line)
        if re.match(r"^    name: ", line):
            jobs[line.split("name:", 1)[1].strip().strip('"')] = current
    return jobs


def _steps(job: list[str]) -> list[list[str]]:
    steps: list[list[str]] = []
    for line in job:
        if re.match(r"^      - ", line):
            steps.append([line])
        elif steps and line.startswith("        "):
            steps[-1].append(line)
    return steps


def _all_jobs() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        found |= _jobs(path.read_text(encoding="utf-8").splitlines())
    return found


def _gated_after_changes(name: str, job: list[str]) -> list[list[str]]:
    """The job's steps after its `changes` step (which must come first after checkout)."""
    steps = _steps(job)
    at = next(
        (i for i, s in enumerate(steps) if any("uses: ./.github/actions/changes" in x for x in s)),
        None,
    )
    assert at is not None, (
        f"{name}: its first step after checkout decides (.github/actions/changes)"
    )
    assert all(
        "actions/checkout@" in s[0] or "Every backend job passed" in s[0] for s in steps[:at]
    ), f"{name}: only checkout comes before the deciding step"
    return steps[at + 1 :]


def test_heavy_jobs_report_at_once_on_prs_and_work_in_the_queue() -> None:
    jobs = _all_jobs()
    assert set(jobs) >= HEAVY, sorted(HEAVY - set(jobs))
    for name in HEAVY:
        steps = _steps(jobs[name])
        changes = next(s for s in steps if any("actions/changes" in x for x in s))
        assert any(x.strip() == 'queue-only: "true"' for x in changes), f"{name}: queue-only"
        for step in _gated_after_changes(name, jobs[name]):
            # `!= 'false'` too: steps shared by YAML anchor with a nightly job that has no
            # deciding step (there the output is empty, so they run).
            gated = ("steps.changes.outputs.run == 'true'", "steps.changes.outputs.run != 'false'")
            assert any(g in x for x in step for g in gated), (
                f"{name}: every step after the deciding one waits for it: {step[0].strip()}"
            )


def test_a_required_check_is_never_skipped_as_a_whole() -> None:
    """A job-level `if:` that skips would never report; only `always()` is allowed there."""
    jobs = _all_jobs()
    for name in REQUIRED:
        job_ifs = [x for x in jobs[name] if re.match(r"^    if: ", x)]
        assert all("always()" in x for x in job_ifs), f"{name}: job-level {job_ifs}"


def test_gating_workflows_do_not_run_again_on_push_to_main() -> None:
    for workflow in GATING:
        triggers = _triggers((WORKFLOWS / workflow).read_text(encoding="utf-8").splitlines())
        assert "push" not in triggers, f"{workflow}: the queue already tested the merge commit"
        assert "schedule" in triggers, f"{workflow}: a nightly run catches outside changes"
        assert "merge_group" in triggers, f"{workflow}: every merge is tested in the queue"
