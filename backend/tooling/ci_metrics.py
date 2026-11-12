"""Daily CI numbers for the repository, read-only (`make ci-metrics DAYS=1`).

Per UTC day, for the last DAYS days (today, so far, is the last row):

- queue runs / queue ok: ci.yml runs on the merge_group event, all and successful;
- PRs merged: pull requests merged that day (`gh pr list --state merged`);
- groups: merge groups that landed. Approximate: with the merge method "merge" the queue
  fast-forwards main to the group's head commit, which is the merge commit of the group's last
  pull request; so a group landed when a successful merge_group run's head SHA is the merge
  commit of a merged pull request. Distinct such SHAs, by the run's day;
- avg group: PRs merged that day / groups landed that day;
- PR shard min: runner minutes of jobs named "backend tests ..." in pull_request ci.yml runs
  created that day, re-run attempts included (what CI test selection is meant to cut).

Only `gh run list`, `gh pr list` and `gh api` GETs: it never changes anything. The gh calls go
through one function, so the unit tests run it on recorded JSON without a network.
"""

import argparse
import csv
import json
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import astuple, dataclass, fields
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = "Extravis-islamabad/supportx-v2"
WORKFLOW = "ci.yml"
SHARD_JOB = "backend tests "
LIMIT = "1000"

Gh = Callable[[list[str]], str]


def gh(args: list[str]) -> str:
    """Run a read-only gh command and return its output."""
    done = subprocess.run(  # noqa: S603 - fixed gh subcommands from this module, no shell
        ["gh", *args],  # noqa: S607 - gh from PATH, like the Makefile
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout


@dataclass(frozen=True)
class Day:
    """One UTC day's numbers."""

    day: str
    queue_runs: int
    queue_ok: int
    prs_merged: int
    groups: int
    avg_group: float | None
    pr_shard_minutes: float


def _day(stamp: str | None) -> str:
    return (stamp or "")[:10]


def _time(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp)


def _runs(run: Gh, repo: str, event: str, since: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = json.loads(
        run(
            [
                "run",
                "list",
                "--repo",
                repo,
                "--workflow",
                WORKFLOW,
                "--event",
                event,
                "--created",
                f">={since}",
                "--limit",
                LIMIT,
                "--json",
                "databaseId,conclusion,createdAt,headSha",
            ]
        )
        or "[]"
    )
    return found


def _merged(run: Gh, repo: str, since: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = json.loads(
        run(
            [
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "merged",
                "--search",
                f"merged:>={since}",
                "--limit",
                LIMIT,
                "--json",
                "number,mergedAt,mergeCommit",
            ]
        )
        or "[]"
    )
    return found


def _shard_seconds(run: Gh, repo: str, run_id: int) -> float:
    """Seconds the run's backend shard jobs held a runner, every attempt."""
    out = run(
        [
            "api",
            "--paginate",
            f"repos/{repo}/actions/runs/{run_id}/jobs?filter=all&per_page=100",
            "--jq",
            f'.jobs[] | select(.name | startswith("{SHARD_JOB}")) | {{started_at, completed_at}}',
        ]
    )
    seconds = 0.0
    for line in out.splitlines():
        if not line.strip():
            continue
        job = json.loads(line)
        if job.get("started_at") and job.get("completed_at"):
            seconds += (_time(job["completed_at"]) - _time(job["started_at"])).total_seconds()
    return seconds


def collect(run: Gh, days: int, *, today: date, repo: str = REPO) -> list[Day]:
    """The numbers per day, oldest first."""
    dates = [(today - timedelta(days=n)).isoformat() for n in reversed(range(days))]
    since = dates[0]
    queue = [r for r in _runs(run, repo, "merge_group", since) if _day(r["createdAt"]) in dates]
    merged = [p for p in _merged(run, repo, since) if _day(p["mergedAt"]) in dates]
    landed_commits = {(p.get("mergeCommit") or {}).get("oid") for p in merged} - {None}
    groups: dict[str, set[str]] = defaultdict(set)
    for r in queue:
        if r["conclusion"] == "success" and r["headSha"] in landed_commits:
            groups[_day(r["createdAt"])].add(r["headSha"])
    shard_seconds: dict[str, float] = defaultdict(float)
    for r in _runs(run, repo, "pull_request", since):
        if _day(r["createdAt"]) in dates:
            shard_seconds[_day(r["createdAt"])] += _shard_seconds(run, repo, r["databaseId"])
    rows: list[Day] = []
    for d in dates:
        prs = sum(1 for p in merged if _day(p["mergedAt"]) == d)
        landed = len(groups[d])
        rows.append(
            Day(
                day=d,
                queue_runs=sum(1 for r in queue if _day(r["createdAt"]) == d),
                queue_ok=sum(
                    1 for r in queue if _day(r["createdAt"]) == d and r["conclusion"] == "success"
                ),
                prs_merged=prs,
                groups=landed,
                avg_group=round(prs / landed, 2) if landed else None,
                pr_shard_minutes=round(shard_seconds[d] / 60, 1),
            )
        )
    return rows


HEADERS = ("day", "queue runs", "queue ok", "PRs merged", "groups", "avg group", "PR shard min")


def table(rows: list[Day]) -> str:
    """The rows as an aligned text table."""
    cells = [HEADERS, *(tuple("-" if v is None else str(v) for v in astuple(r)) for r in rows)]
    widths = [max(len(row[i]) for row in cells) for i in range(len(HEADERS))]
    return "\n".join(
        "  ".join(c.rjust(w) for c, w in zip(row, widths, strict=True)) for row in cells
    )


def write_csv(rows: list[Day], path: Path) -> None:
    """The rows as CSV, one column per field."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([f.name for f in fields(Day)])
        writer.writerows(astuple(r) for r in rows)


def main(argv: list[str] | None = None, *, run: Gh = gh, today: date | None = None) -> int:
    """Print the table (and the CSV when asked)."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--days", type=int, default=1, help="how many days back (default 1)")
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--csv", type=Path, help="also write the rows as CSV here")
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error("--days must be at least 1")
    rows = collect(run, args.days, today=today or datetime.now(UTC).date(), repo=args.repo)
    sys.stdout.write(table(rows) + "\n")
    if args.csv is not None:
        write_csv(rows, args.csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
