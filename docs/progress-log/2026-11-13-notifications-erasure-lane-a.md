### 2026-11-13 — An erased person's notifications go (lane A, WP-056)

Lane C found that an erased person's delivered notifications stayed, the account-security ones
with a device and a city among them. The notifications module now consumes
`identity_access.user.status_changed` and, for reason `erasure` only, deletes the person's in-app
entries and delivery rows and takes them off rules that name them; per tenant (RLS), idempotent;
a plain deactivation keeps the history. Their e-mails' content goes with the mail sender's own
retention purge. No migration (DELETE was already granted). Test:
tests/db/test_notifications_erasure.py.

Rules that named the person drop them as a versioned change with the rules' live signal, so a
stale admin save cannot put them back (lane B's review). Still open, for Haider: notification
titles are stored rendered, so other people's entries can carry the erased person's name
("Aisha assigned you ..."); mail bodies at erasure are lane B's port (with the person-level
erasure work, audit gap #12), and preferences stay (on/off switches, no content).
