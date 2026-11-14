### 2026-11-14 — Lane B: erasure mention polish (trashed rows, short names, 0170)

Follow-ups from the reviews of #511 and #514, approved by the coordinator as one bundle with
migration 0170.

- **Trashed rows in lane B's mention ports** (the rule lane A used in #514): a soft-deleted
  person's profile, a soft-deleted file's name, and a note that is trashed (or whose asset is)
  are found, and their passage and redaction work for `people.erase` holders only; live rows
  keep their normal rights. Files gained `include_deleted` on `live_names`, `file_name` and
  `rename_for_erasure`.
- **Short names** (the coordinator's rule): the full first + last name is always searched; a
  one-word display name on its own only from 4 characters (counted by character, so Arabic and
  Urdu by letter). The report carries `short_name_not_searched` as a flag, never the name; the
  screen names it from the person row (`people_erasure.short_name_not_searched`, with
  `{{name}}`) or, once erased, `people_erasure.short_name_not_searched_erased`.
- **Task mentions** carry `reaches_record_history` (`people_erasure.reaches_record_history`):
  redacting one also blanks its record's task history naming the person.
- **0170** replaces `history_child_rows`: a phone is compared per phone-like run of digits (old
  and new values joined with ` | `, so a run never spans the two), no longer across all of a
  value's digits; the name rule as above. Callers are unchanged; the downgrade restores 0167's
  body.
- Tests: trashed profile, file and note readable only by an eraser, redacted; the report flag
  and no stored name; the short-name rule (Latin and Arabic); the per-run phone match and
  name rule in task history.
