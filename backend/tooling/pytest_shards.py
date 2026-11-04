"""pytest plugin: split the backend suite into balanced CI shards, and record file timings.

The backend suite outgrew one CI job (26 minutes of tests on 2026-10-27, the job limit 30), so CI
runs it as N parallel jobs, each with its own PostgreSQL, Valkey, NATS and object store, and each
using pytest-xdist inside (product owner, 2026-10-27: the backend CI job under 15 minutes).

- `SUPPORTX_TEST_SHARD=i/N` (1-based) keeps the test files of shard i. Files are assigned whole
  (their session and module fixtures are built once), heaviest first, each to the shard with the
  least time so far, using the seconds in `tests/shard_weights.json`. A file not listed there
  weighs DEFAULT_SECONDS. The assignment depends only on the collected file names and the
  weights, so every shard computes the same split without talking to the others.
- Tests that use the private Keycloak (`private_keycloak`, tests/integration) share one
  xdist group, so with `--dist loadgroup` one worker per shard starts one Keycloak (about 1 GB
  and 20 seconds), never one per worker.
- `SUPPORTX_TEST_TIMINGS=<path>` writes how long each file took (call phases plus fixtures) as
  JSON. CI keeps each shard's as an artifact; `make backend-shard-weights` refreshes the weights
  from a CI run (CI's runners, not a laptop, are what the shards must balance on).

Registered with `-p tooling.pytest_shards` (pyproject addopts); does nothing without the
variables. Never imported by the app.
"""

import json
import os
import statistics
from collections import defaultdict
from pathlib import Path

import pytest

WEIGHTS = Path(__file__).resolve().parents[1] / "tests" / "shard_weights.json"
DEFAULT_SECONDS = 5.0  # only when there are no weights at all
# Above this share of unweighted files the split is mostly guesswork: CI warns to refresh them.
UNWEIGHTED_WARN_SHARE = 0.10


def _shard() -> tuple[int, int] | None:
    raw = os.environ.get("SUPPORTX_TEST_SHARD", "").strip()
    if not raw:
        return None
    index, _, total = raw.partition("/")
    shard, count = int(index), int(total)
    if not 1 <= shard <= count:
        msg = f"SUPPORTX_TEST_SHARD={raw}: expected i/N with 1 <= i <= N"
        raise pytest.UsageError(msg)
    return shard, count


def _file(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def fallback_seconds(weights: dict[str, float]) -> float:
    """What a file without a weight counts: the median measured file, not a fixed guess.

    New test files are mostly ordinary database tests; 5 s made a shard of them look light
    until it ran past the job's limit (2026-11-04, 97 of 234 files unweighted).
    """
    return statistics.median(weights.values()) if weights else DEFAULT_SECONDS


def unweighted(files: list[str], weights: dict[str, float]) -> list[str]:
    """The files the weights don't know yet."""
    return [name for name in files if name not in weights]


def assign(files: list[str], weights: dict[str, float], count: int) -> dict[str, int]:
    """Each file's shard (1-based): heaviest first, onto the lightest shard so far."""
    default = fallback_seconds(weights)
    load = [0.0] * count
    placed: dict[str, int] = {}
    ordered = sorted(files, key=lambda name: (-weights.get(name, default), name))
    for name in ordered:
        lightest = min(range(count), key=lambda shard: (load[shard], shard))
        load[lightest] += weights.get(name, default)
        placed[name] = lightest + 1
    return placed


KEYCLOAK_GROUP = "keycloak"


@pytest.hookimpl(tryfirst=True)  # before xdist reads the groups
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Group the private Keycloak's tests; keep only this shard's files (SUPPORTX_TEST_SHARD)."""
    for item in items:
        if "private_keycloak" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.xdist_group(KEYCLOAK_GROUP))
    shard = _shard()
    if shard is None:
        return
    index, count = shard
    weights = json.loads(WEIGHTS.read_text()) if WEIGHTS.is_file() else {}
    files = sorted({_file(item.nodeid) for item in items})
    placed = assign(files, weights, count)
    missing = unweighted(files, weights)
    if files and len(missing) / len(files) > UNWEIGHTED_WARN_SHARE:
        config.stash[_UNWEIGHTED] = (len(missing), len(files))
    kept = [item for item in items if placed[_file(item.nodeid)] == index]
    dropped = [item for item in items if placed[_file(item.nodeid)] != index]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    items[:] = kept


_UNWEIGHTED = pytest.StashKey[tuple[int, int]]()


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    """Warn when the shard weights are stale (more than UNWEIGHTED_WARN_SHARE unknown files)."""
    found = config.stash.get(_UNWEIGHTED, None)
    if found is None:
        return
    missing, total = found
    note = (
        f"{missing} of {total} test files have no shard weight: refresh tests/shard_weights.json "
        "(make backend-shard-weights, from the nightly's backend-shard-weights artifact)"
    )
    terminalreporter.write_line(f"WARNING: {note}", yellow=True)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        terminalreporter.write_line(f"::warning title=Stale shard weights::{note}")


class _Timings:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.seconds: dict[str, float] = defaultdict(float)

    @pytest.hookimpl
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        # Called in the controller for xdist workers too; setup and teardown hold the fixtures.
        self.seconds[_file(report.nodeid)] += report.duration

    @pytest.hookimpl
    def pytest_sessionfinish(self) -> None:
        if os.environ.get("PYTEST_XDIST_WORKER"):
            return  # the controller writes the whole picture
        ordered = dict(sorted((name, round(sec, 1)) for name, sec in self.seconds.items()))
        self.path.write_text(json.dumps(ordered, indent=2) + "\n")


def pytest_configure(config: pytest.Config) -> None:
    """Record file timings when asked (SUPPORTX_TEST_TIMINGS)."""
    if target := os.environ.get("SUPPORTX_TEST_TIMINGS"):
        config.pluginmanager.register(_Timings(Path(target)), "supportx-test-timings")
