### 2026-10-29 — WP-020f QA fix round (lane A)

- QA report ~/Desktop/qa-wp020f/QA-REPORT.md (6 bugs). Branch `fix/wp-020f-qa` on
  `feat/wp-020e` (local until the repository move is done). Each bug got a failing test named
  after it, then a fix of its cause.
- BUG-01: incoming requester replies are "received" (one rule, `reply_is_inbound`). Migration
  0040 adds the state and moves existing ones, per tenant (D-113).
- BUG-02 (lane A part): per-tenant requester channels with a reason, and a `DeliveryListener` that
  starts the auto-close clock on a delivered resolution notice. Admin › Closing shows the reason.
  Lane B wires e-mail.
- BUG-03: the requester's confirm, reject and reply are theirs (person, channel,
  `requester_action`), never "Automatic". `source_of` maps the portal client to "portal".
- BUG-04: only the requester's confirmation or auto-close sets "Confirmed by requester". 422
  `requester_only` on the server; shown unavailable, with the reason, in the Close dialog and bulk close.
- BUG-05: list-fields returns level and closure codes with their naming; chips and the view
  builder pick them by name; reports group by closure code.
- BUG-06: "Closed at" on the record.
- Follow-ups with what unblocks them are in the QA report: WP-028 for plain replies and
  requester cancel; lane B's e-mail part for auto-close end to end; #120 for open work.
- Checks: lint and typecheck green; backend 1797 passed, 8 skipped (Testcontainers); frontend all green (console 335). Full `make check` waits for the QA lock (lane B, WP-023/024 QA).
