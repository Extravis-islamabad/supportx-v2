### 2026-10-29 — WP-024 email channel, session 3: delivery state, waiting, resend (lane B)

Plan ~/Desktop/wp-024-s3-plan.md. Defaults: D-116 (10) to (13), approved. (9), sending as the
mailbox, waits for the product owner.
- **Reply delivery state (REQ-INC-059):**
  - a new reply is queued, or waits while outgoing mail is not set up (it never shows the old
    "not sent" placeholder); the engine links each requester e-mail to its reply (`entry_id`);
  - the sender emits `system.mail.state_changed` (sent, retrying, failed with a code) and the
    reply follows through the incident source's `delivery_changed`;
  - ordering: an older report is ignored and a sent reply never moves back; each change bumps
    the entry's version and reaches the timeline live
    (`work_items.conversation.delivery_changed`).
- **Waiting (REQ-INC-060):** e-mails waiting 7 days fail as `not_sent_in_time`, visibly, and are
  never sent late. `GET /notifications/mail-status` gives staff whether mail works, how many
  wait, and who can fix it (names only).
- **Resend:** `notifications.resend_entry` queues the failed e-mail again to the person's current
  address. It refuses when nothing failed (a double click sends once) or when mail is still not
  set up. Lane A writes the route (audit, If-Match, Idempotency-Key).
- **Migration 0043:** delivery states and reasons, `delivery_updated_at`, `entry_id` on
  deliveries. It moves pre-WP-024 replies from "not sent" to "waiting", per tenant, with a
  reversible downgrade (tested).
- **Tests:** 8 PostgreSQL tests for the delivery flow, and the migration's data step both ways.
  Lane A's two tests now expect "waiting" (for their review).
- **Still to do:** lane A's timeline chips, resend route and composer notice (after their
  queue); sending as the mailbox (D-116 (9)) once the product owner answers.
