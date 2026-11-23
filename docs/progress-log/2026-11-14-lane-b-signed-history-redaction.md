### 2026-11-14 — Lane B: signed history redaction (ADR-046 addendum, 0167)

Plan A of the erasure follow-ups, approved by the coordinator (migration 0167). Built on #506
(S1b); the migration sits on 0164 and is re-pointed at its turn.

- **Migration 0167:** `field_change_redactions` (tenant, RLS forced, SELECT only for the app),
  `audit_verification_runs.fingerprints_redacted`, a unique (tenant_id, id) on
  `person_erasure_mentions`, and the definer `history_redact_signed(mention, rows, old, new,
  salted)`. It has the binding of 0164's `history_redact_field`, accepts only signed rows of the
  mention's own record and field, stores the digests, then blanks. The downgrade refuses while
  any tenant has a row.
- **Audit:** `redact_signed_history` computes the digests as the fingerprint does (salted for a
  personal field). The verifier puts kept digests in place of values (`FieldValues.old_digest /
  new_digest`, byte layout unchanged) and reports `redacted_on_request` only with a logged
  `person.erasure_mention_redacted` after the entry; else mismatch. Runs count it; labels
  `audit_fingerprint_status.redacted_on_request` en/ar/ur.
- **identity_access:** `redact` blanks the signed rows through audit's public interface when
  `history_redact_field` kept some; `SIGNED_HISTORY_REDACTION` is on. The refusal
  `erasure_signed_history_kept` stays for any row still kept.
- **Tests:** tests/db/test_signed_history_redaction.py (4) and
  tests/db/test_signed_history_redaction_migration.py (1); fingerprint golden vectors unchanged.

- **Task history (found in #514's review):** a task's text lives in its parent work item's
  history (`task` = the title, `task.<field>` = old/new values; no task ID in the rows), which
  `history_redact_field` (by the mention's own record type) never reached. 0167 adds
  `history_child_rows(mention)` and `history_redact_child(mention)`: for a redacted
  `work_item_task` mention, the parent's `task` / `task.*` rows whose values contain the person's
  name, address or phone (last 9 digits). The person is read inside the function from the
  mention's own erasure, never passed in (the coordinator, 2026-11-14), so no caller can widen
  what is blanked. Signed ones go through `history_redact_signed`, which accepts those rows too.
  Test: rows naming the person blanked (signed ones with kept digests), the other task's history
  untouched, idempotent, nothing for an unredacted or non-task mention or a closed erasure.
- The registry marks a mention redacted before calling its port and passes `mention_id`, so a
  port's definer bound to the redacted mention (lane C's 0168) can act from inside the port.
