### 2026-10-28 — WP-039 QA round and WP-023 session 1 (lane B)
- **WP-039 QA** on the shared stack (~/Desktop/qa-wp039/QA-REPORT.md):
  - the e2e journeys pass 10/10;
  - the lock-out message is identical for a wrong password, an unknown address and a locked
    account in en, ar and ur;
  - deactivation ends sessions at once.
  - **5 bugs for WP-039-FIX:** an old invitation link still works after a resend; a withdrawn
    link shows the lock-out text; **at the idle limit the screen does not sign out**
    (`IdleWatcher`); Urdu Keycloak pages are mostly English; the Arabic update-password
    title says "Password updated".
- **WP-023 session 1:** see the WP entry. D-106 is pending review.
- **CI follow-ups (#96, merged):**
  - the shard weights now come from CI's own timings, and the shards are even;
  - 2 workers per shard were 10–25% slower than 4, so CI keeps 4.
