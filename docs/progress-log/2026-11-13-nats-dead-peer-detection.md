### 2026-11-13 — NATS notices a lost node in about 30 s; sessions from a later release still read (lane B)

On branch fix/nats-dead-peer-detection (worktree supportx-v2-natsping), from main. No migration.

- **Found:** the HA node-loss test's fan-out step failed 3 times (PR runs of #461, #466 and #472,
  NodeLocal DNSCache in for the last). The fan-out's new copy started about 50 s after the loss
  but stayed not ready past 90 s. A NATS server was on the stopped node every time, and NATS ran
  with its defaults: servers and nats-py clients ping every 2 min and give up after 2 missed
  pings. A powered-off node never closes its connections, so its peers could take about 4 min to
  notice. Until then a JetStream leader on it is not replaced, and JetStream calls (the
  fan-out's provisioning at start) time out.
- **Fix:** the chart's NATS servers run `ping_interval: 10s`, `ping_max: 3` (all profiles). The
  workers' bus connection uses the same (`workers/bus.py`). A lost peer is found in about 30 s.
- **Test output:** node-loss.sh prints the JetStream meta, events-stream and fan-out consumer
  leaders before the stop and after the fan-out check. On failure it prints them and the
  fan-out's log. The HA diagnostics print the fan-out's logs.
- **Rolling updates (lane C's S1b finding, #459):** `Session.from_dict` ignores fields a later
  release added, never a TypeError. It must reach main before S2a, which adds fields.
- **Tests:** a unit test that the bus connects with 10 s x 3; a session with a later release's
  fields reads back equal; the golden render carries the two NATS settings.
