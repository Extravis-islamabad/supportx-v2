"""Timing limits for tests: strict at night, generous in pull requests (product owner, 2026-10-28).

Strict millisecond targets flaked on CI's shared 2-vCPU runners, where four test workers run
beside each other under coverage tracing (#79, #85). So a timing test asserts
`elapsed < limit(target)`:

- in a pull request, `limit` is ten times the target: a real regression (a several-fold
  slowdown) still fails, load on a shared runner does not;
- in the nightly performance run (`.github/workflows/perf.yml`, `SUPPORTX_PERF_STRICT=1`: one
  process, no coverage, a machine of its own) it is the target itself, and the measured values go
  to the job summary and an artifact, so trends show over time.

Timing tests carry `@pytest.mark.timing`, which the nightly run selects.
"""

import fcntl
import json
import os
import tempfile
import warnings
from pathlib import Path
from typing import Any

PR_FACTOR = 10


def strict() -> bool:
    """Whether this is the nightly performance run."""
    return os.environ.get("SUPPORTX_PERF_STRICT") == "1"


def volume(full: int, smoke: int) -> int:
    """How many rows or events a volume test makes: all of them nightly, a smoke run in PRs.

    The full volumes (100k list rows, 10k relay events) took about 90 s of a PR shard for a
    number only the nightly run asserts strictly; a pull request keeps a small run of the same
    code path at the generous PR bound (coordinator, 2026-11-10).
    """
    return full if strict() else smoke


def limit(target: float) -> float:
    """The bound to assert against for a timing whose target is `target`."""
    return target if strict() else target * PR_FACTOR


def record(name: str, values: Any) -> None:  # noqa: ANN401 - any JSON-ready measurements
    """Add `values` under `name` to the run's report (SUPPORTX_PERF_REPORT), if one is asked for.

    The nightly run shows the report in its summary and keeps it as an artifact, for trends.
    Test workers run in parallel (pytest-xdist): each update holds a lock beside the report and
    replaces the file atomically, so no worker reads another's half-written file. A report that
    cannot be written is a warning, never a failed test: the test asserts its timing, not this.
    """
    target = os.environ.get("SUPPORTX_PERF_REPORT")
    if not target:
        return
    path = Path(target)
    try:
        with path.with_suffix(path.suffix + ".lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            found = json.loads(path.read_text()) if path.is_file() else {}
            found[name] = values
            fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
            try:
                with os.fdopen(fd, "w") as out:
                    json.dump(found, out, indent=2, sort_keys=True)
                Path(temporary).replace(path)
            finally:
                Path(temporary).unlink(missing_ok=True)
    except (OSError, ValueError) as error:  # ValueError: a report left broken by an older run
        warnings.warn(f"timing report not written: {error}", stacklevel=2)
