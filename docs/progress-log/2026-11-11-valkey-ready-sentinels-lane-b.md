### 2026-11-11 — WP-014b follow-up: a Valkey pod is Ready only once its sentinel knows it (lane B)

- **Why:** Sentinel learns a master's replicas only from the master's INFO, every 10 s (fixed in
  Valkey 9.1.2). A pod could be Ready, and a rolling update or drain stop the master, before the
  sentinels knew its replicas: `-failover-abort-no-good-slave` until the master returned. #388
  only made the HA tests wait for the sentinels; this fixes the chart.
- **Chart (`templates/valkey-ha.yaml`):** the valkey container's readiness probe is the new
  `ready.sh` beside `valkey.sh` and `sentinel.sh`. Read-only, a few local `valkey-cli` calls, same
  period (5 s) and timeout:
  - `/run/valkey/waiting` present → prints it, not ready (#284, unchanged); PING must answer;
  - first readiness gate, until passed in the current role, asking this pod's own sentinel
    (localhost:26379, same auth as `sentinel.sh`): a replica must be synced
    (`master_link_status:up`) and listed by `SENTINEL replicas supportx` as `<SELF>:6379`, not
    down or disconnected; a master needs every `connected_slaveN` host listed the same way. A
    master with no connected replica passes at once (lane B review): replicas connecting later
    pass their own gate, and a ready master never flips to not ready over its sentinel;
  - passing writes `/run/valkey/ready-role` (the role); then only the server counts, so a
    sentinel blip never makes Valkey unready. A different role clears the mark and gates again;
    `valkey.sh` clears it at every container (re)start (the emptyDir outlives the container).
- **Tests (`backend/tests/ha/test_valkey_failover.py`):** a master with its sentinel held back is
  not ready, then ready once its sentinel lists both replicas; a replica restarted, waited for
  only through `ready.sh`, then the master stopped: the failover succeeds and the promoted pod
  gates again as master; a lone pod is ready; a ready master whose sentinel is shut down stays
  ready and takes writes. #284's guard tests unchanged.
- **Docs:** the remaining gap (an unplanned master crash within about 10 s of a fresh start;
  no data lost) in `docs/deployment.md`, Profiles.
