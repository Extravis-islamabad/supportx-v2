### 2026-11-13 — WP-046a S5c: kept drafts on the server (lane A)

REQ-INC-019, migration 0160, on lane C's field encryption (#482). Lane B's conditions: a fixed
list of forms, 64 KB before sealing and a save limit per person, deletion on deactivation or
erasure, owner-only access (admins too), nothing of a draft in logs, plain values only, a signal
with the form and version only, and only the sender's own draft removed on save. Lane C's: a
role-status note above the first field, a confirmation before replacing typing, Discard of both
copies, the person's date format, Discard only when unreadable, nothing shown without a key, no
"saved" chatter, and matrix states for both notes.

Test note: the field cipher's per-process key cache holds a Valkey client, so db tests that use
it run with `valkey_url` off (each test has its own event loop).
