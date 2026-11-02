### 2026-10-28 — Backend CI in parallel shards, PR #76 (lane B; product owner priority)

- The backend gate is three jobs: `backend checks` (lint, schema checks, mypy, migrate + RLS
  guard), `backend tests 1/3..3/3` (each with its own services, `pytest -n 4 --dist loadgroup`;
  files balanced by `tests/shard_weights.json` through `tooling/pytest_shards.py`), and the
  required `backend` (every job passed, coverage of all shards combined, 90 % enforced).
- Timings: before, 27.7 min (#72) and 38.3 min (#70) in one job; after, checks 1.1 min, shards
  4.1 / 3.5 / 5.8 min, gate done 6.8 min after the run starts.
- Found on the way: parallel database bootstraps failed with "tuple concurrently updated"
  (cluster-wide roles); `db_bootstrap` holds an advisory lock. A CPU-bound timing test measured
  wall-clock time under parallel load; it measures its own CPU time now.
- The 100k-row audit volume test runs nightly only (audit-scale.yml, 10M). New test-only
  dependencies: pytest-xdist, execnet (MIT, D-012). Lanes A and C told to merge main.
