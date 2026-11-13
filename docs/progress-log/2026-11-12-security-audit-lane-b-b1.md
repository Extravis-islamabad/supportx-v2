### 2026-11-12 — Security audit, lane B bundle B1 (rows 26, 27, 14 follow-ups)

On branch fix/security-audit-b1 (worktree supportx-v2-secB1), from main after #447. No migration.

- **API-key HMAC key (row 26):** `SUPPORTX_API_KEY_SECRET` is required in production (at least 32
  characters); dev and test still derive one from `SUPPORTX_SESSION_SECRET`. Upgrades break no
  key: a key hashed under the old derived key is verified with it and re-hashed under the new
  key on its first good call (guarded by the old hash), while the session secret stays set. The
  chart passes `api-key-secret` (optional ref, so a missing one gets the app's clear refusal);
  `deploy/scripts/secrets.sh` makes it for new installs and adds it to existing Secrets.
  Operators' notes: docs/api/keys.md.
- **Refresh-token rotation (row 26):** both realm files and the `keycloak-identity` Job set
  `revokeRefreshToken: true`, `refreshTokenMaxReuse: 0`. The BFF already stored each new token;
  two races are closed: a request that finds the refresh lock held answers without saving its
  stale copy, and one that takes the lock after another's refresh uses the stored token.
- **Idempotency-Key on saving an audit search.** The `KNOWN_GAPS` guard file named in the plan
  (`tests/test_create_routes_idempotent.py`) is not on main, so there was no row to remove.
- **IPv6 per /64** in `ip_rate_limit`; IPv4 and IPv4-mapped per address.
- **A rate-limited callback** goes back to the portal, tenant address or mobile app it started
  from (the pending sign-in read without spending it); with Valkey down, the console.
- **Semgrep (row 27):** `.semgrep.yml`, `.semgrepignore`, `make semgrep` (official image pinned
  by version and digest), a non-required `static analysis (Semgrep)` job in security.yml. The 11
  findings on main were all safe: 8 `nosemgrep` with reasons, 3 merged migrations excluded by
  exact path.
- **Skipped:** the LDAP host pin (row 3): `app/shared/egress/sockets.py` is not on main yet.
