### 2026-11-14 — Lane B: GDPR person erasure S1b (mentions report and redaction)

- **Scope:** ADR-052 S1b (D-171 a), server side only (no screens): the mentions report shown to
  the approver and redaction of chosen passages. Migration 0164 (down revision 0161).
- **Built:**
  - `PersonMentions` port in person_data.py (`find_mentions`, `redact_mention`, `passage`),
    `Mention`, `MentionBatch`, `MENTION_BATCH` (500), `register_mentions`, and
    `REQUIRED_MENTION_PORTS` (identity_access, assets, files, work_items
    (one key, lane A's review), integrations, knowledge, announcements). Terms (`MentionTerms`) come from
    the person's row when needed (display name, first + last, e-mail, phone and mobile as
    digits) and are never stored. Matching and redaction are pure (domain/mentions.py).
  - Migration 0164: `person_erasure_mentions` (RLS forced; SELECT, INSERT, UPDATE only; one row
    per place and kind; states found, redacted, left; index (tenant_id, erasure_id, state)),
    `person_erasures.report_reviewed_at / report_reviewed_by`, a unique (tenant_id, id) on
    `person_erasures` for the composite key. The downgrade refuses while any tenant has a
    mention or a reviewed report.
  - The report build runs in the existing 30 s erasure schedule for requested erasures: every
    registered port in key order, one batch per transaction, progress in `report.building`;
    a port registered later runs on the next tick and the review lapses.
  - Approval refuses `erasure_report_unavailable` (no report, or not complete) and
    `erasure_report_not_reviewed`; approval leaves found mentions as `left`; the job's step 0
    refuses an incomplete report. With S1b's registry no report is complete: approval stays
    refused until S2 (tested).
  - Routes: `POST /erasures/{id}/report/reviewed`, `GET /erasures/{id}/mentions`,
    `GET /erasures/{id}/mentions/{mention_id}/passage`, `POST /erasures/{id}/mentions/redact`;
    audit actions `person.erasure_report_reviewed`, `person.erasure_mention_viewed`,
    `person.erasure_mention_redacted` (IDs only). `attachment_content_searched: false` on the
    report and the list, labelled `people_erasure.attachment_content_not_searched`.
  - Lane B's ports: identity_access (other people's description, job title, signature; the
    person's own row skipped; passage needs `users.view`, the description `users.manage`),
    files (names only; redaction renames; passage needs the right to see the file), assets
    (asset notes, deleted ones searched but shown no passage).
  - Labels en/ar/ur for every new code; the `erasure_report_unavailable` text now says the
    report is not complete.
- **Changes to the brief:** `redact_mention` also takes `terms` (it must know what to replace,
  and terms are never stored). Mention ports run in key order (they have no bands). The review
  is allowed on an incomplete but finished report (it records what the admin saw).
- **Definer functions (after #500's `create_definer_function` landed):**
  - `history_redact_field(mention)`: blanks the values of the one record and field a redacted
    mention row names, in the caller's tenant; called by `redact` right after each port's own
    redaction. Rows a fingerprinted audit entry commits to are kept and counted in the mention's
    `history_kept` (shown with `people_erasure.history_kept_fingerprinted`): blanking them would
    read as tampering until the verifier gets a `redacted_on_request` status (follow-up).
  - `audit_erase_profile_history(person)`: blanks values and reasons of the person's own profile
    history, guarded by `users.erased_at`; called in step 6 (count
    `profile_history_rows_erased`).
  - Tests: only the mention's field blanked (another field on the same record, a fingerprinted
    row and tenant B untouched); an unredacted or unknown mention changes nothing; profile
    history untouched before `erased_at`, blanked after, idempotent, unreachable from tenant B;
    the whole-job test checks step 6.
  - D-171 keeps no redacted original: approval and job start refuse an erasure whose redaction
    kept a signed history row (`erasure_signed_history_kept`, labelled en/ar/ur, tested) until
    the verifier follow-up lands (the coordinator, 2026-11-14).
- **Not done:** asset descriptions and loan/audit comments are not searched (they describe the
  asset, not people); S2 may add them. A phone number written next to other digits (a date
  run into it) is not matched.
- **Reviews on #506 (lane C, lane A, coordinator):**
  - `history_redact_field` now requires the mention's `redacted_at` and `redacted_by` and an
    erasure in a redactable state, and narrows the signed-row check by `object_id` (lane C).
  - `passage` honours field access: a registry backstop by record type and field, plus the
    users resource's own field rules in the users port (lane A).
  - One `work_items` mention key; an index pre-filter is allowed if it never misses an exact
    match; rich text is matched and redacted between tags only (`count_matches_html`,
    `redact_html`, used for asset notes); a redaction that would overflow its field is refused
    (`erasure_redaction_too_long`), never cut (lane A).
  - The report says inbound mail bodies were not searched (`mail_bodies_searched: false`,
    `people_erasure.mail_bodies_not_searched`), as for attachment contents (coordinator).
