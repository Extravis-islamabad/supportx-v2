### 2026-11-13 — Lane B polish 9

- `deploy/k3d/node-loss.sh`: when the fan-out's new copy is not ready in time (or does not
  acknowledge events), the test now prints, for every fan-out copy off the stopped node, its
  conditions and container states, its recent events, its logs, and its own `/readyz` answer
  through the API server's pod proxy. Three runs failed here with only the dead copy's logs to
  read (43307414807, 131530642943, 43462162931); the next one says what the new copy waits on.
