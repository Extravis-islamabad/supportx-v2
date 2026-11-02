### 2026-10-29 — WP-024 email channel, session 1 (lane B)
Plan: ~/Desktop/wp-024-plan.md. Defaults: D-109, approved with customer-registered OAuth apps
and the held-mail review queue as MVP.
- **Mailboxes** (`integrations` module, migration 0037 after main's 0036): IMAP with TLS by
  default and plain only when allowed (audited), passwords sealed with the installation key
  ring. Admin › Mail shows each mailbox's state and reason and how much mail waits, with
  add/change/test/remove, refusals at the form, the shared conflict dialog and live updates on
  the tenant channel (Arabic counts in six forms).
- **Fetching** every 2 minutes. A message is changed on the server only after it is stored, and
  the `mail_fetched` ledger makes each message count once. Loops (our own addresses), floods,
  too-large mail and automatic mail (out-of-office, bounces, lists) create nothing. Strangers
  follow the mailbox's policy and get a polite answer.
- **Incidents** (work_items implements the inbound port; lane A reviews):
  - new mail becomes an incident in the requester's name, with channel e-mail and the
    mailbox's group as entry group (#110);
  - the requester's reply lands on its incident through `add_requester_reply` (#105). It
    resumes or reopens the incident; a late reply starts a follow-up whose ID is answered to
    the sender in their language;
  - an out-of-office is recorded, moves nothing and notifies nobody;
  - a technician's mail on a record is held ("not the requester");
  - a refused create is held with the fields a template or rule needs.
- **Threading:** notification e-mail subjects carry "[INC-12]". A reply without the token is
  matched by In-Reply-To/References against the delivery log (`notifications.records_for_mail`).
  The quoted history is dropped.
- **Review queue** (D-109 (9)): held and too-large mail per mailbox, each with its reason. An
  admin hands it in again (no flood check) or discards it; both are audited. Held mail keeps its
  copy until then.
- **Docs:** `docs/guides/mail-oauth-apps.md`, a step-by-step guide to the customer's own
  Microsoft Graph and Gmail apps (session 2 uses them).
- **Tests:**
  - parser and routing units;
  - ledger, policy, RLS, fetch state, queue and follow-up answer on PostgreSQL;
  - the real incident services;
  - the mailbox API;
  - the IMAP reader against a private GreenMail (test-only image);
  - console tests.
  Full `make check` green: 1732 passed, 7 skipped, all opt-in (volume and load variables,
  WeasyPrint).
- **Session 2:** Microsoft Graph and Gmail, attachments from mail. Next for lane B: the
  dev-profile Mailpit on k3d (product owner), which turns the skipped cluster mail tests back on
  (#125's `SUPPORTX_E2E_MAIL_URL`).
