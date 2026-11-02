### 2026-10-28 — CI follow-ups: shard weights from CI, 2 vs 4 workers (lane B, #96)
- Each backend shard now keeps its file timings as an artifact; `make backend-shard-weights`
  rebuilds `tests/shard_weights.json` from a CI run (the old weights, from a laptop, summed to
  ~300 s against 4,309 worker-seconds on CI; shard 3 carried 2,047, shard 2 736).
- Test step per shard before (6 main runs): slowest 370–581 s, spread up to 2.3x (214 vs 491).
  After (3 runs): 488/480/444, 494/486/420, 483/351/406 s: even shards; the slowest shard is
  within the runners' own noise of before (~8 minutes).
- 2 workers per shard (same commit, side by side, twice): 617/590/453 and 546/500/407 s against
  4 workers' 494/486/420 and 483/351/406; one 2-worker shard failed (an order-dependent
  assertion in `test_auth_bff.py`, fixed). **Kept 4 workers.**
- Two strict timings left in `test_filters.py` (50 ms, 10 ms) now use `tooling/timing.py`
  (10x in PRs, the target nightly).
