### 2026-11-13 — Lane B polish 5: CI numbers that survive a gone run, allow-list before refresh

On branch fix/lane-b-polish-5 (worktree supportx-v2-polish5), from main. No migration.

- **ci-metrics:** a pull_request run whose jobs the API no longer returns is counted in a new
  `unread` column and left out of the shard minutes, never the end of the report (DAYS=7 stopped
  on run 43093087219). `--failures` lists each failed queue run with the jobs that failed in it.
- **Sign-in session refresh:** the IP allow-list is checked before the token refresh, not after,
  so an address about to be refused never costs a refresh-token rotation (lane C's #451 note).
- **chart-lint:** the "external database without caSecret is refused" case now checks that the
  refusal names `postgresql.external.caSecret`, so an unrelated refusal can't pass it (lane C,
  #467).
- **values.yaml:** an operator's own breached-password ConfigMap is capped at 1 MiB too (lane C,
  #471).
