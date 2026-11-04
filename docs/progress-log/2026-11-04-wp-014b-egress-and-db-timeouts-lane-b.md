### 2026-11-04 — WP-014b: bounded database waits and the opt-in egress allow-list (lane B, #195)

- **Database waits** (`app/core/database.py`, shared, agreed with the coordinator; lanes A and C checked their code):
  - the application pool gets a 10 s connect and a 120 s command limit (settings);
  - the reporting pool's limit is the longest report plus 60 s;
  - the index and SLA-timer engines are unchanged.

  Tests: a server that goes silent mid-connection fails a query in about 2 s (it hung without the limit), and a connect fails within 1 s.
- **Egress allow-list:** off by default. The design was approved by the coordinator for the product owner, with three changes, all built:
  1. the Kubernetes API at its real addresses (an EndpointSlice lookup, or `kubeApiCidrs`; the chart refuses otherwise, never `0.0.0.0/0`);
  2. ClamAV can't fail silently: a NOTES warning, a `malware_signatures` warning in /ready after 48 h, and a signature-age gauge;
  3. docs: addresses only, the proxy pattern, an example on-prem allow-list.

  The HA CI cluster runs with egress on, and `egress-check.sh` shows the outside blocked. The first cluster run found the API and worker pods' wait-for-migrate needing the Kubernetes API, and freshclam needing its source; both are fixed.
- **Product owner, 2026-11-04:**
  - D-126 (Dependabot auto-merge rules) written;
  - #189's gitleaks false positive ignored by its exact fingerprint;
  - WP-013's checklist gets "re-enable the pre-upgrade licence check".
- **Follow-ups:**
  - the alert rule for `supportx_files_signature_age_seconds` comes with WP-014b session 3 (monitoring), as the chart has no alert rules yet;
  - D-126's auto-merge step for Dependabot PRs is not built.
- **Resume:** WP-014b session 2: CloudNativePG backups and PITR, SeaweedFS with rclone, the restore runbook, the pre-upgrade Job, the upgrade test.
