### 2026-11-04 — WP-041 public API: API keys, scopes, the contract's security (lane C, D-128)

- API keys in `identity_access`: the `sxk_` format (tenant first, so the key is found under
  row-level security), an HMAC-SHA-256 of the secret under a server key, shown once and never
  stored (not even for an idempotent replay), scopes per area that narrow the owner's live
  grants, expiry (90 days by default, at most a year), an optional IP allowlist, and revoke at
  once. Migration 0055 with FORCE RLS and its isolation test.
- Keys never reach browser-only routes (session, profile, realtime tokens, the key screens).
  A missing scope answers `api_scope_missing`, naming a scope the key lacks.
- Made and revoked keys go through the outbox and reach key managers' list and the owner's own
  channel live; a change to the two tenant rules sends a tenant-wide signal. Audited: made,
  revoked, refused, rules changed.
- OpenAPI: `ApiKey` and `BrowserSession` schemes, `x-scopes` on every operation; oversized page
  sizes reduced with `X-Page-Size-Capped`; `make api-errors` for the error codes;
  docs/api/README.md and keys.md.
- Secret scanning: the key pattern is a gitleaks rule, and the security workflow proves a sample
  key is caught by that rule.
- Screens: Admin › API keys (every key; the two tenant rules for whoever may change sign-in
  settings) and My profile › API keys (one's own, when allowed): per-area read or write, the
  one-time display with copy, revoke after a confirmation. Labels in en, ar and ur.
- Reviewed by lane B (identity parts and the security workflow step); their three points are in.
