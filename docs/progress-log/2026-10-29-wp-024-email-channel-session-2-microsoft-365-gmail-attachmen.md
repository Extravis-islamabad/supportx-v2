### 2026-10-29 — WP-024 email channel, session 2: Microsoft 365, Gmail, attachments (lane B)

Defaults: D-116 (approved 2026-10-29). Draft PR #133.
- **Microsoft 365 and Gmail mailboxes** (`integrations`, migration 0042, expand only):
  - the customer's own OAuth app per mailbox, with a client secret or a Microsoft certificate
    (RS256 client assertion), sealed with the installation key ring;
  - Graph with application permission or delegated, and Gmail delegated, with the least
    scopes (`Mail.ReadWrite` and `gmail.modify`);
  - readers fetch raw MIME, so the parser, ledger and routing are shared with IMAP.
- **Consent:**
  - "Sign in as the mailbox" on Admin > Mail, with PKCE;
  - a one-time hashed state, valid ten minutes for the admin who started it, on the same
    address;
  - the account must be the mailbox;
  - the callback `/api/v1/integrations/oauth/callback` (and the login callback) are left out of
    tracing, because the code is in the query.
- **Never silent:**
  - a failing mailbox notifies the people with `mailboxes.manage` once per new reason
    (notification events `mailbox.failing` and `mailbox.credential_expiring`);
  - an app secret or certificate is announced 14 days before it expires;
  - the mail page shows the kind of mailbox, the sign-in state and the expiry.
- **Attachments from mail** through WP-022's upload path as the sender:
  - screened against the tenant's rules first, and refused files named on the record in the
    sender's language;
  - one savepoint per file;
  - storage outages leave the mail on the server.
  - The inbound port's `reply_from_mail` returns `Replied(entry_id, follow_up)`; reply files go
    on the conversation entry (lane A's `RequesterReply`, merged with main 2026-11-02).
- **Tests:**
  - `fake_providers` (Microsoft identity, Graph, Google OAuth and Gmail as an httpx
    MockTransport; no network, no real account);
  - 19 unit tests;
  - 11 PostgreSQL tests: API, callback refusals, another tenant, mail into incidents, the
    failing notice, expiry, attachments on real S3-compatible storage;
  - console tests.
- **Waiting on lane A:**
  - requesters may attach to their own record, and work_items' file access registers at import
    (lane A's `fix/requester-file-access`). Until it lands, `test_mail_attachments_go_through_the_files_path_and_refusals_are_named`
    fails; it passes with that branch applied.
  - `RequesterReply` (lane A's `fix/wp-020f-qa`) for entry-level reply files.
- **API:** host, port and user name are nullable, listed as accepted breaks under D-109 (D-095).
- **Session 3:** outgoing mail per mailbox (REQ-INT-053), delivery state and resend
  (REQ-INC-059), the composer without mail (REQ-INC-060).
