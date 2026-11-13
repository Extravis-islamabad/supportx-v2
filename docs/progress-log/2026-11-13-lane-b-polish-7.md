### 2026-11-13 — Lane B polish 7

- e2e `signInAs`: the wait after the reload that resets a suite user's language and theme uses
  `FIRST_LOAD_AFTER_SIGN_IN_MS` too: it is a full app load, as right after sign-in (lane A's note
  on #484).
- `deploy/k3d/ci-backup-store.sh up`: a restarted store that came back on another address now
  warns that the release needs `helm upgrade -f <values>` before its next backup, because the
  egress allow-list (a /32) and the endpoint still name the old address (lane C's note on #484).
