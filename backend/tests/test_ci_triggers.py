"""The required checks report on every pull request and in the merge queue.

A required check that never reports blocks a merge forever: a path-filtered workflow did that to
docs-only PRs (#112), and a workflow without the `merge_group` trigger would do it to every PR in
the merge queue. Heavy jobs decide inside, with their first step (`.github/actions/changes`).
The names are the required status checks on `main` (the ruleset); keep both lists equal. Speed
mode (D-122) took "core profile, integration and e2e" out of them until the pilot (WP-043).

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


# --- Speed mode (D-122): heavy jobs run nightly and on demand, never as a merge gate ----------

# Too slow to gate every merge until the pilot (WP-043 brings them back as required). They run
# nightly on main, on a manual run and on a PR labelled `full-ci`; a job-level `if:` skips them
# everywhere else, so they take no runner. None may be a required check.
LABELLED = {
    "core profile, integration and e2e ${{ matrix.shard }}/3",  # three shards, by time
    "images (build, Trivy, SBOM)",
    "ldap federation",  # WP-040, D-130
    "k3d install and smoke test",
    "pdf (worker image)",
    "worker resilience",
}
# The HA jobs follow deployment and Valkey changes instead of the label (the coordinator,
# 2026-11-05): a migration PR labelled full-ci needs the core profile and e2e, not the HA
# cluster. They run nightly, manually and on every PR, where their first step (the changes
# action) finishes at once unless the PR touches deployment or Valkey.
BY_PATH = {
    "k3d HA smoke (Valkey failover)",  # WP-014b, ADR-038: failover, node loss, restore drill
    "valkey failover",  # WP-014b, ADR-038
}
# Paths each of them must react to (the `needs:` pattern of its changes step).
BY_PATH_NEEDS = ("deploy/", "backend/app/core/valkey\\.py", "backend/tests/ha/")
HEAVY = LABELLED | BY_PATH
FULL_CI = "contains(github.event.pull_request.labels.*.name, 'full-ci')"
# Workflows with required checks: the queue tested the merge commit, so no push run on main.
GATING = ("ci.yml", "security.yml")
NIGHTLY_ONLY = ("stack-smoke.yml", "cluster.yml")


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


def _all_jobs() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        found |= _jobs(path.read_text(encoding="utf-8").splitlines())
    return found


def _job_if(job: list[str]) -> str:
    return " ".join(x for x in job if re.match(r"^    if: ", x))


def test_heavy_jobs_run_nightly_and_with_the_label_only() -> None:
    jobs = _all_jobs()
    assert set(jobs) >= HEAVY, sorted(HEAVY - set(jobs))
    for name in LABELLED:
        condition = _job_if(jobs[name])
        for needed in ("'schedule'", "'workflow_dispatch'", FULL_CI):
            assert needed in condition, f"{name}: runs on {needed}"
        assert "merge_group" not in condition, f"{name}: never gates the queue"


def test_ha_jobs_follow_deployment_changes_not_the_label() -> None:
    jobs = _all_jobs()
    for name in BY_PATH:
        job = jobs[name]
        condition = _job_if(job)
        for needed in ("'schedule'", "'workflow_dispatch'", "'pull_request'"):
            assert needed in condition, f"{name}: runs on {needed}"
        assert "full-ci" not in condition, f"{name}: not pulled in by the label"
        assert "merge_group" not in condition, f"{name}: never gates the queue"
        text = "\n".join(job)
        assert "uses: ./.github/actions/changes" in text, f"{name}: decides from the PR's files"
        needs = next(x for x in job if x.strip().startswith("needs: '"))
        for path in BY_PATH_NEEDS:
            assert path in needs, f"{name}: reacts to {path}"
        # Every step after checkout and the changes step is skipped when it says so, including
        # steps reused through a YAML alias (`- *free-disk`): their anchor carries the guard.
        unguarded = [
            step[0].strip()
            for step in _steps(job)[2:]
            if not any("steps.changes.outputs.run" in x for x in step)
            and not _guarded_alias(step[0])
        ]
        assert unguarded == [], f"{name}: steps run without the changes guard: {unguarded}"


def _steps(job: list[str]) -> list[list[str]]:
    """The job's steps, each as its lines (a step starts at `      - `)."""
    found: list[list[str]] = []
    for line in job:
        if line.startswith("      - "):
            found.append([line])
        elif found and line.startswith("        "):
            found[-1].append(line)
    return found


def _guarded_alias(first: str) -> bool:
    """Whether a `- *anchor` step's anchor, wherever it is defined, has the changes guard."""
    alias = re.match(r"^      - \*([a-z0-9-]+)$", first)
    if alias is None:
        return False
    for path in sorted(WORKFLOWS.glob("*.yml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if line.strip() == f"- &{alias.group(1)}":
                body = lines[index + 1 : index + 4]
                return any("steps.changes.outputs.run" in x for x in body)
    return False


def test_no_heavy_job_is_a_required_check() -> None:
    assert not HEAVY & REQUIRED


def test_a_required_check_is_never_skipped_as_a_whole() -> None:
    """A job-level `if:` that skips would never report; only `always()` is allowed there."""
    jobs = _all_jobs()
    for name in REQUIRED:
        condition = _job_if(jobs[name])
        assert condition == "" or "always()" in condition, f"{name}: job-level {condition}"


def test_adding_the_label_starts_the_heavy_jobs() -> None:
    for workflow in ("ci.yml", *NIGHTLY_ONLY):
        lines = (WORKFLOWS / workflow).read_text(encoding="utf-8").splitlines()
        types = " ".join(_triggers(lines)["pull_request"])
        assert "labeled" in types, f"{workflow}: {types}"
        assert "synchronize" in types, f"{workflow}: {types}"


def test_no_workflow_runs_again_on_push_to_main() -> None:
    for workflow in (*GATING, *NIGHTLY_ONLY):
        triggers = _triggers((WORKFLOWS / workflow).read_text(encoding="utf-8").splitlines())
        assert "push" not in triggers, f"{workflow}: the queue already tested the merge commit"
        assert "schedule" in triggers, f"{workflow}: runs nightly"
    for workflow in NIGHTLY_ONLY:  # no required check there: the queue need not wait for it
        triggers = _triggers((WORKFLOWS / workflow).read_text(encoding="utf-8").splitlines())
        assert "merge_group" not in triggers, workflow


def test_the_mobile_job_is_gated_through_the_required_frontend_check() -> None:
    """#236: mobile/** runs only the mobile job; the required `frontend` check carries it."""
    jobs = _all_jobs()
    mobile = "\n".join(jobs["mobile"])
    assert "mobile" not in REQUIRED  # no ruleset change (a GitHub setting, Haider's)
    assert "uses: ./.github/actions/changes" in mobile
    assert "needs: '^(mobile/|frontend/packages/" in mobile
    frontend = "\n".join(jobs["frontend"])
    assert "needs: [mobile]" in frontend
    assert "always()" in _job_if(jobs["frontend"])
    assert "success|skipped" in frontend  # anything else fails the required check


def test_a_mobile_only_change_skips_the_backend_and_frontend_jobs() -> None:
    jobs = _all_jobs()
    for name in ("backend checks", "backend tests ${{ matrix.shard }}/6", "backend", "frontend"):
        text = "\n".join(jobs[name])
        assert "light: '^(docs/|mobile/|" in text, name


# Drafts run the fast set only (coordinator, 2026-11-06: runners were starved). These skip on a
# draft and run again at ready_for_review; the queue always runs them.
DRAFT = "github.event.pull_request.draft"
SKIPPED_ON_DRAFTS = {
    "shard weights",
    "backend tests ${{ matrix.shard }}/6",
    "valkey failover",
    "k3d HA smoke (Valkey failover)",
}
# Required checks report on drafts (never skipped as a whole) but skip every step.
STEPS_SKIPPED_ON_DRAFTS = {"dependency audit (pip-audit, pnpm audit)", "filesystem scan (Trivy)"}


def test_drafts_skip_the_heavy_jobs() -> None:
    jobs = _all_jobs()
    for name in SKIPPED_ON_DRAFTS:
        assert DRAFT in _job_if(jobs[name]), name
    for name in STEPS_SKIPPED_ON_DRAFTS:
        job = jobs[name]
        assert any(DRAFT in line for line in job), name
        steps = [line for line in job if re.match(r"^      - (uses|name): ", line)]
        guarded = [line for line in job if "env.DRAFT != 'true'" in line]
        assert len(guarded) == len(steps), f"{name}: every step skips on a draft"


def test_the_backend_check_allows_skipped_shards_on_drafts_only() -> None:
    backend = "\n".join(_all_jobs()["backend"])
    assert f"DRAFT: ${{{{ (github.event_name == 'pull_request' && {DRAFT}) }}}}" in backend
    assert '[ "$DRAFT" = "true" ] && [ "$TESTS" = "skipped" ]' in backend


def test_marking_a_draft_ready_runs_every_pr_workflow_again() -> None:
    for path in sorted(WORKFLOWS.glob("*.yml")):
        triggers = _triggers(path.read_text(encoding="utf-8").splitlines())
        if "pull_request" in triggers:
            types = " ".join(triggers["pull_request"])
            assert "ready_for_review" in types, f"{path.name}: {types}"
