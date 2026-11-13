"""The daily CI numbers (tooling/ci_metrics.py), on recorded gh output: no network, no writes."""

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from tooling import ci_metrics

TODAY = date(2026, 11, 12)

QUEUE = [
    {
        "databaseId": 1,
        "conclusion": "success",
        "createdAt": "2026-11-11T09:00:00Z",
        "headSha": "c2",
    },
    {
        "databaseId": 2,
        "conclusion": "failure",
        "createdAt": "2026-11-11T10:00:00Z",
        "headSha": "x1",
    },
    {
        "databaseId": 3,
        "conclusion": "success",
        "createdAt": "2026-11-12T08:00:00Z",
        "headSha": "c3",
    },
    {
        "databaseId": 4,
        "conclusion": "success",
        "createdAt": "2026-11-12T08:05:00Z",
        "headSha": "y9",
    },
    {
        "databaseId": 5,
        "conclusion": "success",
        "createdAt": "2026-11-10T08:05:00Z",
        "headSha": "old",
    },
]
MERGED = [
    {"number": 10, "mergedAt": "2026-11-11T09:20:00Z", "mergeCommit": {"oid": "c1"}},
    {"number": 11, "mergedAt": "2026-11-11T09:20:00Z", "mergeCommit": {"oid": "c2"}},
    {"number": 12, "mergedAt": "2026-11-12T08:30:00Z", "mergeCommit": {"oid": "c3"}},
    {"number": 9, "mergedAt": "2026-11-10T08:30:00Z", "mergeCommit": None},
]
PR_RUNS = [
    {
        "databaseId": 100,
        "conclusion": "success",
        "createdAt": "2026-11-11T07:00:00Z",
        "headSha": "p",
    },
    {
        "databaseId": 101,
        "conclusion": "failure",
        "createdAt": "2026-11-12T07:00:00Z",
        "headSha": "q",
    },
]
JOBS: dict[int, list[dict[str, str | None]]] = {
    100: [
        {"started_at": "2026-11-11T07:01:00Z", "completed_at": "2026-11-11T07:11:00Z"},
        {"started_at": "2026-11-11T07:01:00Z", "completed_at": "2026-11-11T07:06:00Z"},
    ],
    101: [{"started_at": "2026-11-12T07:01:00Z", "completed_at": None}],
}


FAILED_JOBS: dict[int, tuple[str, ...]] = {2: ("backend tests 3/8",)}


class Recorded:
    """Answers the gh calls ci_metrics makes from the recordings above, and logs them."""

    def __init__(self, gone: frozenset[int] = frozenset()) -> None:
        self.calls: list[list[str]] = []
        self.gone = gone  # runs whose jobs the API no longer returns

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        if args[:2] == ["run", "list"]:
            event = args[args.index("--event") + 1]
            return json.dumps(QUEUE if event == "merge_group" else PR_RUNS)
        if args[:2] == ["pr", "list"]:
            return json.dumps(MERGED)
        if args[0] == "api":
            run_id = int(args[2].split("/runs/", 1)[1].split("/", 1)[0])
            if run_id in self.gone:
                raise subprocess.CalledProcessError(1, ["gh", *args])
            if "filter=latest" in args[2]:  # the failed jobs of a queue run
                return "".join(f"{name}\n" for name in FAILED_JOBS.get(run_id, ()))
            return "\n".join(json.dumps(job) for job in JOBS[run_id]) + "\n"
        raise AssertionError(args)


def test_the_numbers_per_day() -> None:
    gh = Recorded()
    rows = ci_metrics.collect(gh, 2, today=TODAY)
    assert rows == [
        ci_metrics.Day("2026-11-11", 2, 1, 2, 1, 2.0, 15.0),
        ci_metrics.Day("2026-11-12", 2, 2, 1, 1, 1.0, 0.0),
    ]
    # Read-only: listing runs and PRs, and GETs on the API (gh api without --method).
    for call in gh.calls:
        assert call[0] in {"run", "pr", "api"}
        assert call[:2] in (["run", "list"], ["pr", "list"]) or "--method" not in call
    assert any(f">={'2026-11-11'}" in call for call in gh.calls)


def test_a_day_without_groups_has_no_average() -> None:
    rows = ci_metrics.collect(Recorded(), 3, today=TODAY)
    assert rows[0] == ci_metrics.Day("2026-11-10", 1, 1, 1, 0, None, 0.0)


def test_the_cli_prints_a_table_and_writes_csv(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "ci.csv"
    assert ci_metrics.main(["--days", "2", "--csv", str(target)], run=Recorded(), today=TODAY) == 0
    out = capsys.readouterr().out
    assert "PR shard min" in out
    assert "2026-11-12" in out
    lines = target.read_text().splitlines()
    assert lines[0] == (
        "day,queue_runs,queue_ok,prs_merged,groups,avg_group,pr_shard_minutes,unread"
    )
    assert lines[1] == "2026-11-11,2,1,2,1,2.0,15.0,0"
    with pytest.raises(SystemExit):
        ci_metrics.main(["--days", "0"], run=Recorded(), today=TODAY)


def test_gh_is_called_without_a_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    class Done:
        stdout = "[]"

    def fake_run(command: list[str], **_: object) -> Done:
        seen.append(command)
        return Done()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert ci_metrics.gh(["run", "list"]) == "[]"
    assert seen == [["gh", "run", "list"]]


def test_a_run_the_api_no_longer_returns_is_counted_never_fatal() -> None:
    """One expired run used to stop the whole report (DAYS=7, run 43093087219, 2026-11-13)."""
    rows = ci_metrics.collect(Recorded(gone=frozenset({100})), 2, today=TODAY)
    assert (rows[0].pr_shard_minutes, rows[0].unread) == (0.0, 1)
    assert (rows[1].pr_shard_minutes, rows[1].unread) == (0.0, 0)


def test_failed_queue_runs_name_their_failed_jobs(capsys: pytest.CaptureFixture[str]) -> None:
    found = ci_metrics.failed_queue_runs(Recorded(), 2, today=TODAY)
    assert found == [ci_metrics.FailedRun("2026-11-11", 2, "x1", ("backend tests 3/8",))]
    gone = ci_metrics.failed_queue_runs(Recorded(gone=frozenset({2})), 2, today=TODAY)
    assert gone[0].jobs == ("unread",)
    assert ci_metrics.main(["--days", "2", "--failures"], run=Recorded(), today=TODAY) == 0
    assert "failed queue run 2 (2026-11-11, x1): backend tests 3/8" in capsys.readouterr().out
