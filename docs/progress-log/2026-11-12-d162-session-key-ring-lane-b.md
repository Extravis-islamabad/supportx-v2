### 2026-11-12 — D-162: a rotatable sign-in key ring (lane B)

- **Format (ADR-048):** `app/shared/crypto`: a pure codec (v2 blob = 0x02, key ID, nonce,
  AES-256-GCM under HKDF-SHA256 per purpose; associated data binds purpose, key ID and
  NUL-separated `bound_to` parts; text form `sx2:` + base64url), a `KeyRing` (newest seals, any
  listed key opens) and the "who still uses key X" hook. Lane C's WP-057 reuses it.
- **Sessions:** `SessionCipher` seals v2 under the newest key of `SUPPORTX_SESSION_KEYS`
  (`SUPPORTX_SESSION_SECRET` alone = the ring `legacy`); v1 records open read-only while
  `legacy` is listed; every save re-seals. The worker's session ender uses the same ring.
- **Untangled:** cursors and API-key hashes fall back only to `SUPPORTX_SESSION_SECRET`, byte
  for byte as before; domain proofs take the new `SUPPORTX_DOMAIN_PROOF_SECRET`, else that
  secret. Production refuses `SUPPORTX_SESSION_KEYS` without `SUPPORTX_SESSION_SECRET` unless the
  API-key, cursor and domain-proof secrets are all set. Settings errors no longer echo their
  input.
- **Audit (migration 0146):** `session_key_ids` and `session_key_events` (platform tables),
  `session_key_announcements` (tenant table, RLS). Start-up only claims a change (ON CONFLICT DO
  NOTHING / conditional UPDATE ... RETURNING, the winner records the event); the schedule
  `identity_access__session_key_announce` writes `security.session_key_rotated` / `_retired`
  into each tenant's log, the entry and the tenant's announcement row in one transaction, so a
  crash or two runs at once never lose or repeat one. The first start claims nothing. A removed
  key a registered user still counts refuses start-up (`session_key_still_in_use`). `/ready`
  warns above three keys.
- **Lane C's notes:** every ring key but `legacy` needs 32 bytes (settings and ring builder);
  `bound_to` needs at least one part. A test proves a refused start-up never prints a secret.
- **Chart:** `secrets.sessionKeys` lists IDs and Secret keys; values and manifests never hold a
  secret; empty = as before (golden unchanged).
- **Docs:** ADR-048, D-162, docs/guides/rotating-the-sign-in-key.md, docs/deployment.md.
- **Open:** migration 0146's `down_revision` is "0140" and is re-pointed at queue time.
