### 2026-11-04 — Secret-scan scope, stack-smoke shards, WP-040 LDAP paused (lane B)

- **#177, merged:** PR and merge-queue secret scans now read only their own commits. The nightly and manual runs still scan every commit on every branch. `.gitleaksignore` holds exactly one fingerprint: a made-up test value in commit `2f23862`, already replaced in `b19d016`. No rule is disabled and no file is allowlisted (product owner, 2026-11-03). The full manual scan on main found no leaks in 650 commits.
- **#179, open (full-ci):** the stack-smoke job hit its 40-min limit because the suite outgrew one job: 85 journeys take about 45 min even when green. The PR adds two Playwright shards, a 40-min step limit, and Playwright's own 35-min run limit (`E2E_GLOBAL_TIMEOUT_MINUTES`, opt-in). It keeps one retry, and the 60-min job limit is only a backstop. Next: put it on `--auto` once its own stack-smoke run shows both shards finish, then triage automation and branding-admin from the printed errors. `files` is the environment, because the malware scanner isn't answering.
- **#178 (lane A, WP-028):** lane B reviewed and approved its changes to lane B code: portal links in notifications, requesters sent to the portal at sign-in, and own contact details. The e2e user change in `stack.ts` still needs lane B's look.
- **#175 (WP-040 LDAP):** main merged in. 0055 now revises main's head 0051.
  - **Resume:** `integrations/service/ldap_directories.py`, then the consumer that applies it to Keycloak, then the API and screen.
- Parked for the product owner: #169 (D-126, Dependabot).
