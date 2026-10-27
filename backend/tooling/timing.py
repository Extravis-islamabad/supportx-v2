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

import json
import os
from pathlib import Path
from typing import Any

PR_FACTOR = 10


def strict() -> bool:
    """Whether this is the nightly performance run."""
    return os.environ.get("SUPPORTX_PERF_STRICT") == "1"


def limit(target: float) -> float:
    """The bound to assert against for a timing whose target is `target`."""
    return target if strict() else target * PR_FACTOR


def record(name: str, values: Any) -> None:  # noqa: ANN401 - any JSON-ready measurements
    """Add `values` under `name` to the run's report (SUPPORTX_PERF_REPORT), if one is asked for.

    The nightly run shows the report in its summary and keeps it as an artifact, for trends.
    """
    if target := os.environ.get("SUPPORTX_PERF_REPORT"):
        path = Path(target)
        found = json.loads(path.read_text()) if path.is_file() else {}
        found[name] = values
        path.write_text(json.dumps(found, indent=2, sort_keys=True))
