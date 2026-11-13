### 2026-11-13 — Staging laptop runbook (D-169)

On branch docs/staging-laptop-runbook (worktree supportx-v2-staging), from main at 032260df.
Documentation and helper files only; no migration, no app code.

- **Runbook** `docs/runbooks/staging-laptop.md`: Ubuntu Server prep (ufw: SSH and HTTPS from the
  LAN only, no CI runner, no inbound webhook), pinned tools (Helm v4.3.1, uv 0.12.19, Node
  24.22.1, k3s v1.36.5+k3s1), `deploy/k3d/prereqs.sh` on plain k3s, the profile, a laptop CA for
  TLS, secrets, the first install by hand, the nightly job, logs, rollback, laptop updates, and
  what staging is not. Listed in `docs/deployment.md` (new Runbooks table) and `deploy/README.md`.
- **Nightly job** `deploy/staging/nightly.sh` (shellcheck-clean) with
  `supportx-staging.service`/`.timer` (03:00, Persistent, 15 min random delay),
  `staging.env.example` and `traefik-config.yaml` (Gateway API on, websecure kept open for
  realtime, port 80 not exposed, LAN-only load balancer). Pull into a dedicated checkout
  (marker file), build images tagged by commit, `k3s ctr images import`, secrets, `helm upgrade
  --rollback-on-failure --wait`, `helm test`, `/api/v1/ready`; dated logs kept 14 days and a
  status file.
- **Overlay** `deploy/helm/supportx/values-staging.yaml` on `values-single-node.yaml`; added as the
  `staging` profile in `deploy/scripts/chart-lint.sh` (lint + kubeconform green locally).
- **Not yet in the repo** (marked in the runbook): GlitchTip (D-167), `make e2e-smoke`, an image
  bundle or Zot mirror and the offline installer (D-038, WP-014c), a cluster Showcase seed.
