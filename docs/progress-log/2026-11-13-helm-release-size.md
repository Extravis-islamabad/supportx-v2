### 2026-11-13 — The Helm release back under its 1 MiB Secret (lane B)

On branch fix/helm-release-size (worktree supportx-v2-relsize), from main. No migration, no new
dependency.

- **Found:** #467's Cluster run 43345912681 failed `helm install` in the dev and HA jobs:
  `Secret "sh.helm.release.v1.supportx.v1" is invalid: data: Too long`. Helm keeps each release
  as one Secret of base64(gzip(JSON)), with every chart file and the rendered manifest, capped at
  1 MiB. Main was just under the limit. WP-039's breached-password list (456 KB, 47k lines) was in
  it twice: as a chart file and as a 644 KB ConfigMap.
- **Fix:** the list ships in the backend image (`/opt/supportx/keycloak/password-blacklists/`),
  is left out of the chart (`.helmignore`), and the Keycloak pod's `copy-password-blacklists`
  init container copies it into the folder Keycloak reads. An operator's own list is a ConfigMap
  named in `keycloak.passwordBlacklists.configMap`. The dev Compose stack and the tests still
  mount the repo file.
- **Guard (chart-lint):** (packaged chart + gzipped manifest) × 4/3 must stay under 750 KB for
  the ha-ci, ha, single-node and dev profiles: about 363 KB now, about 1.0 MB on main before. The
  list must never be in the chart or its render. The golden file loses the ConfigMap.
- **Docs:** the list's README and docs/architecture/identity.md.
