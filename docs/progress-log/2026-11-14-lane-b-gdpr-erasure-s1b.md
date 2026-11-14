### 2026-11-14 — Lane B: GDPR person erasure S1b (mentions report and redaction)

- **Scope:** ADR-052 S1b (D-171 a), server side only (no screens): the mentions report shown to
  the approver and redaction of chosen passages. Migration 0164 (down revision 0161).
- **Built:**
  - `PersonMentions` port in person_data.py (`find_mentions`, `redact_mention`, `passage`),
    `Mention`, `MentionBatch`, `MENTION_BATCH` (500), `register_mentions`, and
    `REQUIRED_MENTION_PORTS` (identity_access, assets, files, work_items.references,
    work_items.owned, integrations, knowledge, announcements). Terms (`MentionTerms`) come from
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
- **Design note, pending definer functions (not built; the guard refuses them outside the
  code-owned helper that lands with another PR):**
  - `history_redact_field(record_type, record_id, field)`: migrator-owned SECURITY DEFINER, sets
    `old_value` and `new_value` to NULL on every earlier `field_changes` row of that one field,
    so a redacted passage does not survive in history; called by each port's `redact_mention`
    after its own history row; the app role gets EXECUTE only.
  - `audit_erase_profile_history(person_id)`: the same for the erased person's own profile
    history (`field_changes` of record type `user`) and its copies in audit entries, called
    from step 6.
  Both are marked TODO in migration 0164.
- **Not done:** asset descriptions and loan/audit comments are not searched (they describe the
  asset, not people); S2 may add them. A phone number written next to other digits (a date
  run into it) is not matched.
