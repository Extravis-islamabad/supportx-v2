### 2026-10-28 — Invitation links after "Send again" (lane B, #113)
- Product owner: "Send again" stops the earlier link where Keycloak allows it, and otherwise the
  screen says so. A private Keycloak 26.8.1 with GreenMail showed that Keycloak cannot withdraw
  one link, even after ending the user's sessions. Only an account made afresh stops it, which
  #104 does for accounts made by the invitation. `tests/integration/test_keycloak_links.py`
  pins both.
- For an account that existed before the invitation, `earlier_links_work` is shown on the
  invitations list and in the "sent again" message (en/ar/ur). Tests cover the API and the
  console.
- CI note (#112, verified with #117): every PR gets all 8 required checks. Docs-only PRs finish
  the heavy jobs at once ("skipped: docs-only change"), and a new push cancels its PR's older runs.
