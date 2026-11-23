### 2026-11-12 — Engineering-practices audit (#444): lane B security fixes, part A

- **Scope:** audit rows 4 (login CSRF), 3 (egress in SaaS only), 14 (auth rate limits, lane B's
  part) and 15 (HSTS on nginx). Branch `fix/security-audit-a`, one commit per item.
- **Row 4, login CSRF:** `/auth/login` and `/auth/account-action` set a binding cookie per
  sign-in (`supportx_login_<16 hex of the state's SHA-256>`, `__Host-` in production; HttpOnly,
  SameSite=Lax, Secure as the session cookie, Path=/, Max-Age 600). The pending state keeps only
  the token's SHA-256; the callback compares in constant time and refuses with the new labelled
  code `login_not_this_browser`; the cookie is cleared on success and failure. One cookie per
  state, so two tabs signing in at once both finish. Not bound: the mobile app's sign-in (its S256
  challenge binds it, ADR-044; it now never ends a browser session it passes through) and the SSO
  test (private window, no session). Docs: docs/architecture/authentication.md.
- **Row 3, egress in SaaS:** not done. There is no SaaS values profile yet (only dev,
  single-node, ha, ha-ci; the SaaS cell is WP-014d). Nothing invented; recorded in PROGRESS.md.
- **Row 14, rate limits:** a reusable per-address dependency `ip_rate_limit` in
  app/shared/api/ratelimit.py (the client address uvicorn resolved through the trusted proxies;
  own `rlip:` keys, address hashed; the same RateLimit-* headers). Sign-in routes 60 a minute
  each and fail closed (503 `sign_in_unavailable`, Retry-After 2; a browser is sent back to its
  app with the code). Public branding (300), domain check (30) and public action links (120, an
  outer cap over their own budgets) fail open. `rate_limit("organization")` on
  `/organization/tenant` and `/organization/settings`. Docs: docs/deployment.md. The route-walk
  test is another lane's (PR #445).
- **Row 15, HSTS:** `Strict-Transport-Security: max-age=63072000; includeSubDomains` at server
  level in deploy/images/nginx.conf (no location sets its own headers), always on. A test parses
  the file and checks every location that adds headers repeats it.
- **Tests:** tests/db/test_auth_bff.py (binding: no cookie, another browser's cookie, cleared,
  two tabs, host prefix), tests/db/test_auth_mobile.py (app sign-in unbound, browser session
  kept), tests/db/test_auth_rate_limits.py, app/shared/api/tests/test_ip_rate_limit.py,
  tests/test_web_headers.py.
