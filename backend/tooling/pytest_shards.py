"""pytest plugin: split the backend suite into balanced CI shards, and record file timings.

The backend suite outgrew one CI job (26 minutes of tests on 2026-10-27, the job limit 30), so CI
runs it as N parallel jobs, each with its own PostgreSQL, Valkey, NATS and object store, and each
using pytest-xdist inside (product owner, 2026-10-27: the backend CI job under 15 minutes).

- `SUPPORTX_TEST_SHARD=i/N` (1-based) keeps the test files of shard i. Files are assigned whole
  (their session and module fixtures are built once), heaviest first, each to the shard with the
  least time so far, using the seconds in `tests/shard_weights.json`. A file not listed there
  weighs DEFAULT_SECONDS. The assignment depends only on the collected file names and the
  weights, so every shard computes the same split without talking to the others.
- Each shard runs `pytest -n 4 --dist loadfile`: a file's tests stay on one worker, so its
  module fixtures (a private Keycloak, about 1 GB and 20-120 s; a seeded stack) are built once
  per file, never once per worker. `--dist loadgroup` with xdist 3.8 and pytest 9 did not group
  at all (a bare probe spread one group over four workers), so a file's Keycloak tests started
  up to four Keycloaks at once (2026-11-10). The `keycloak` xdist group below is kept for the
  split's chain arithmetic only.
- `SUPPORTX_TEST_TIMINGS=<path>` writes how long each file took (call phases plus fixtures) as
  JSON. CI keeps each shard's as an artifact. The nightly combines them (`backend-shard-weights`)
  and every later CI run balances on the newest nightly's (`SUPPORTX_TEST_WEIGHTS`), so the split
  follows the suite without a commit; `make backend-shard-weights` refreshes the committed
  fallback from a CI run (CI's runners, not a laptop, are what the shards must balance on).
- Files using the private Keycloak run serially (one xdist group per shard), so the split
  spreads them over the shards instead of letting one shard's Keycloak chain set its time.
- `SUPPORTX_TEST_SELECT=<selection.json>` (tooling/test_select.py, PR runs only) keeps only the
  listed files when its "all" is false, before the split, so the shards share out just those.
  A missing or unreadable file runs everything with a warning: never silently nothing.

Registered with `-p tooling.pytest_shards` (pyproject addopts); does nothing without the
variables. Never imported by the app.
"""

import json
import os
from collections import defaultdict
from pathlib import Path

import pytest

WEIGHTS = Path(__file__).resolve().parents[1] / "tests" / "shard_weights.json"
DEFAULT_SECONDS = 5.0  # only when there are no weights at all
# How far up the measured files an unweighted one counts (coordinator, 2026-11-10): new files
# without a weight overloaded one shard three times (#216, #262, #307), counted as the median.
UNWEIGHTED_PERCENTILE = 0.9
# The longest list of unweighted files the warning names (the rest as a count).
UNWEIGHTED_LISTED = 40


def _weights() -> dict[str, float]:
    """The file seconds to balance on: the committed ones, overlaid with the nightly's.

    `SUPPORTX_TEST_WEIGHTS` names a JSON file of file seconds. CI resolves the latest nightly's
    `backend-shard-weights` once per run and gives every shard the same file, so all shards
    compute the same split. Its numbers are the freshest for the files it ran; the committed
    tests/shard_weights.json still covers files added since that nightly (2026-11-05: a nightly
    a day old missed 45 files, and the shards ran 8 to 14.5 minutes).
    """
    found: dict[str, float] = json.loads(WEIGHTS.read_text()) if WEIGHTS.is_file() else {}
    given = os.environ.get("SUPPORTX_TEST_WEIGHTS", "").strip()
    if given and Path(given).is_file():
        found |= json.loads(Path(given).read_text())
    return found


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


def fallback_seconds(weights: dict[str, float], name: str | None = None) -> float:
    """What a file without a weight counts: a pessimistic measured file, never a light guess.

    The 90th percentile of the measured files of its kind (database tests against database
    tests, the rest against the rest), so a new file is planned as a heavy one. 5 s, then the
    median (4.7 s), made a shard of new database tests look light until it ran past the job's
    limit (2026-11-04: 97 of 234 files; 2026-11-10: #307's asset tests, about 500 s).
    """
    if not weights:
        return DEFAULT_SECONDS
    kind = _is_db(name) if name is not None else None
    alike = [v for k, v in weights.items() if kind is None or _is_db(k) == kind] or list(
        weights.values()
    )
    ordered = sorted(alike)
    return ordered[min(len(ordered) - 1, int(UNWEIGHTED_PERCENTILE * len(ordered)))]


def _is_db(name: str) -> bool:
    return "/db/" in f"/{name}"


def unweighted(files: list[str], weights: dict[str, float]) -> list[str]:
    """The files the weights don't know yet."""
    return [name for name in files if name not in weights]


def assign(
    files: list[str],
    weights: dict[str, float],
    count: int,
    *,
    serial: frozenset[str] = frozenset(),
    workers: int = 1,
) -> dict[str, int]:
    """Each file's shard (1-based): heaviest first, where the shard would finish soonest.

    A shard runs its files on `workers` xdist workers, so it finishes after its total time over
    the workers, or after its `serial` files if they take longer: those share one xdist group
    (the private Keycloak) and run one after another on a single worker. Spreading them over
    the shards (each starts its own Keycloak, about 20 s) keeps that chain from setting the
    slowest shard's time (2026-11-05: 830 s of Keycloak tests on one worker).
    """
    total = [0.0] * count
    chain = [0.0] * count

    def finish(shard: int, name: str, seconds: float) -> float:
        serial_time = chain[shard] + (seconds if name in serial else 0.0)
        return max(serial_time, (total[shard] + seconds) / workers)

    def put(name: str, shard: int, seconds: float) -> None:
        total[shard] += seconds
        if name in serial:
            chain[shard] += seconds
        placed[name] = shard + 1

    placed: dict[str, int] = {}

    def estimate(name: str) -> float:
        return weights[name] if name in weights else fallback_seconds(weights, name)

    # Measured files, and every serial (private Keycloak) file, weighted or not: heaviest first,
    # where the shard would finish soonest, its Keycloak chain included. Dealing Keycloak files
    # round-robin put several Keycloak containers on one runner at once, and they failed to
    # start (#321's first queue run).
    planned = sorted(
        (n for n in files if n in weights or n in serial), key=lambda n: (-estimate(n), n)
    )
    for name in planned:
        seconds = estimate(name)
        put(
            name,
            min(range(count), key=lambda shard: (finish(shard, name, seconds), shard)),
            seconds,
        )
    # Other unweighted files last, dealt out round-robin from the lightest shard: a guess is
    # never packed onto one shard, however light the guess makes it look.
    rotation = sorted(range(count), key=lambda shard: (finish(shard, "", 0.0), shard))
    rest = sorted(n for n in files if n not in weights and n not in serial)
    for i, name in enumerate(rest):
        put(name, rotation[i % count], fallback_seconds(weights, name))
    return placed


KEYCLOAK_GROUP = "keycloak"


@pytest.hookimpl(tryfirst=True)  # before xdist reads the groups
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Group the private Keycloak's tests; keep only this shard's files (SUPPORTX_TEST_SHARD)."""
    chosen = _selected(config)
    if chosen is not None:
        outside = [item for item in items if _file(item.nodeid) not in chosen]
        if outside:
            config.hook.pytest_deselected(items=outside)
        items[:] = [item for item in items if _file(item.nodeid) in chosen]
    serial: set[str] = set()
    for item in items:
        if "private_keycloak" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.xdist_group(KEYCLOAK_GROUP))
            serial.add(_file(item.nodeid))
    shard = _shard()
    if shard is None:
        return
    index, count = shard
    weights = _weights()
    files = sorted({_file(item.nodeid) for item in items})
    workers = getattr(config.option, "numprocesses", None)
    placed = assign(
        files,
        weights,
        count,
        serial=frozenset(serial),
        workers=workers if isinstance(workers, int) and workers > 0 else 1,
    )
    missing = unweighted(files, weights)
    if missing:
        config.stash[_UNWEIGHTED] = (missing, len(files))
    kept = [item for item in items if placed[_file(item.nodeid)] == index]
    dropped = [item for item in items if placed[_file(item.nodeid)] != index]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    items[:] = kept


_UNWEIGHTED = pytest.StashKey[tuple[list[str], int]]()
_SELECT_WARNING = pytest.StashKey[str]()


def _selected(config: pytest.Config) -> frozenset[str] | None:
    """The test files SUPPORTX_TEST_SELECT keeps, or None for all of them."""
    given = os.environ.get("SUPPORTX_TEST_SELECT", "").strip()
    if not given:
        return None
    try:
        found = json.loads(Path(given).read_text(encoding="utf-8"))
        if found["all"] is True:
            return None
        files = found["files"]
        if found["all"] is not False or not isinstance(files, list) or not files:
            msg = "expected all false with a non-empty list of files"
            raise ValueError(msg)  # noqa: TRY301 - one fallback for every way the file is bad
        return frozenset(str(name) for name in files)
    except (OSError, ValueError, KeyError, TypeError) as error:
        config.stash[_SELECT_WARNING] = (
            f"SUPPORTX_TEST_SELECT={given} could not be used ({error!r}): running every test"
        )
        return None


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    """Name every test file without a shard weight, so the weights get added."""
    if (warning := config.stash.get(_SELECT_WARNING, None)) is not None:
        terminalreporter.write_line(f"WARNING: {warning}", yellow=True)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            terminalreporter.write_line(f"::warning title=Test selection ignored::{warning}")
    found = config.stash.get(_UNWEIGHTED, None)
    if found is None:
        return
    missing, total = found
    listed = ", ".join(missing[:UNWEIGHTED_LISTED])
    more = (
        f" and {len(missing) - UNWEIGHTED_LISTED} more" if len(missing) > UNWEIGHTED_LISTED else ""
    )
    note = (
        f"{len(missing)} of {total} test files have no shard weight ({listed}{more}): add them to "
        "tests/shard_weights.json (make backend-shard-weights, from the nightly's artifact)"
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
    """Record file timings when asked (SUPPORTX_TEST_TIMINGS); check SUPPORTX_TEST_SELECT."""
    # With xdist only the workers collect; reading the selection here too puts a bad file's
    # warning in the controller's summary, where the job log shows it.
    if not os.environ.get("PYTEST_XDIST_WORKER"):
        _selected(config)
    if target := os.environ.get("SUPPORTX_TEST_TIMINGS"):
        config.pluginmanager.register(_Timings(Path(target)), "supportx-test-timings")
