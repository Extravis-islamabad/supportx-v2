# Testing in CI: shards and timing tests

## Backend CI (PR #76)

The required `backend` check needs three jobs:

- `backend checks`: lint, schema drift and breaking-change checks, mypy, migrate and the RLS
  guard.
- `backend tests 1/3..3/3`: each shard has its own PostgreSQL, PgBouncer, Valkey, NATS and object
  store and runs `pytest -n 4 --dist loadgroup`. `tooling/pytest_shards.py` gives each shard
  whole test files, heaviest first, using the seconds in `tests/shard_weights.json`. A new file
  counts 5 seconds until `make backend-test-timings` refreshes the weights.
- `pdf (worker image)`: report PDFs inside the worker image (lane C).

`backend` combines the shards' coverage and enforces 90 %. It always runs, so a failed or
cancelled job fails it instead of being skipped.

Tests run four at a time on two vCPUs under coverage tracing. Write tests that do not depend on
that: no shared fixed names (databases, NATS streams, buckets and Valkey keys are already per
test), and no strict timing (below).

## Timing tests (product owner, 2026-10-28)

Strict millisecond targets do not belong in pull-request runs: on shared runners they flake
(#79, #85). A test that asserts a speed:

```python
import pytest

from tooling import timing


@pytest.mark.timing
async def test_the_list_is_fast(...) -> None:
    ...
    timing.record("my_list", {"p95_ms": p95})  # for the nightly trend
    assert p95 < timing.limit(300)            # target 300 ms
```

- In pull requests, `timing.limit(target)` is **ten times the target**: a real regression (a
  several-fold slowdown) still fails; runner load does not.
- Nightly, `.github/workflows/perf.yml` runs `pytest -m timing` against the **target itself**
  (`SUPPORTX_PERF_STRICT=1`), in one process, without coverage, on a runner of its own. The
  measurements are in the job summary and in an artifact kept 90 days, to compare runs over time.
- Measure CPU time (`time.process_time`) for pure computation and wall-clock time for I/O
  (queries, events). For pure computation, take the fastest of a few batches.
- Playwright: `timingLimit(targetMs)` from `frontend/e2e/stack.ts` follows the same rule. The
  nightly k3d run sets `SUPPORTX_PERF_STRICT=1`.

A timing that proves a behaviour rather than a speed is not a timing test, and it keeps its
assertion: for example "probes share one deadline" (`test_readiness_service.py`) or "the audit
search at 10 million entries" (nightly only, `audit-scale.yml`).
