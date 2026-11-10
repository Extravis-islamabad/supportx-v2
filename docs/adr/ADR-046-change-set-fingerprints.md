# ADR-046: Change-set fingerprints in lifecycle entries — digests of record history inside the entry hash, per-subject salts reachable only through definer functions, erasure that the verifier accepts only when logged

- **Status:** Proposed (WP-064 S2)
- **Date:** 2026-11-11
- **Source:** WP-064; D-150 ("Values and verification", "Erasure"); ADR-027 §3, §5; ADR-045;
  coordinator 2026-11-11 (migration 0129, ADR-046, conditions 1 and 4)
- **Owner:** Haider (Product Owner)

## Context

ADR-045 gives every save of a lifecycle record one chained audit entry naming its events. The
values themselves stay in record history (`field_changes`), which the app may only insert and
read but which anyone holding the database could still rewrite unnoticed. D-150 asks that the
entry hold a fingerprint of the save's change set, so record history becomes tamper-evident,
and that personal data be kept outside the chain behind a salted hash, so erasure stays
possible: after erasure the chain still verifies and shows "erased on request", accepted only
when a later `audit.subject_erased` entry exists.

## Decision

1. **The entry holds digests, never values.** A lifecycle entry gains three columns, all inside
   the entry hash when `fingerprint` is set and absent otherwise (so every entry written before
   0129, and every non-save entry, hashes byte for byte as before):
   - `fingerprint`: `fp1:` + 64 lowercase hex characters (below);
   - `fingerprint_saves`: the change IDs of the saves it covers, in save order (one entry can
     stand for several saves of one record in one request, ADR-045 §3);
   - `personal_subjects`: the user IDs whose salts its personal values use (sorted; empty when
     the saves changed no personal field or the record names nobody).
   In the canonical entry content (ADR-027 §3) they appear as the keys `fingerprint`,
   `fingerprint_saves` and `personal_subjects`. Exports carry them inside the exported entry,
   so `tools/verify_export.py` checks them without change. It cannot recompute a fingerprint
   (exports hold no record history); the live verifier does.
2. **Personal fields per record type** live in one place, `audit/domain/lifecycle.py`
   (`RecordAudit.personal` and `RecordAudit.data_subjects`), for lanes A and C to review:
   - work items, all five types: subject, description, impact details, resolution, a status
     change's reason text, custom field values (`custom.`), a task's title (`task`,
     `task.title`); problems add root cause, symptoms, workaround and the review texts;
     changes and releases add plan sections (`plan.`), a stage's outcome notes and issues, a
     downtime's description. Their data subjects are the record's requester and the person it
     was raised for (`requester_id`, `on_behalf_of_id`), both when both are set;
   - assets: none;
   - people records are not a lifecycle type yet; their name, email and phone join when they
     are, with the person as the subject.
   IDs and codes are never personal (ADR-027: people appear by ID). All personal fields of a
   record share the record's subjects, so the entry's `personal_subjects` is enough to
   recompute every field; per-field subjects would need a new layout (`fp2:`).
   The owning module tells the sink who the subjects are through a resolver it registers with
   `app/shared/history` (`register_subject_resolver`; work_items reads its row from the
   session's identity map, else one read under RLS), so audit reads no other module's table.
3. **Salts per data subject** (`audit_subject_salts`: tenant, subject, a random 16-byte salt,
   created, erased): RLS forced, tenant first in the primary key, and **no right at all for the
   app role**. Three SECURITY DEFINER functions, owned by the migrator with `search_path`
   pinned to `pg_catalog, public` and `EXECUTE` granted to `supportx_app` only (revoked from
   PUBLIC), are the only way in; FORCE RLS keeps each inside `app.tenant_id`:
   - `audit_subject_salts_ensure(uuid[], bytea[])`: get or create. The app passes a fresh
     `os.urandom(16)` per subject; an existing salt is never replaced; an erased subject gets
     no salt back (so a later save treats them as no subject). Refuses without a tenant.
   - `audit_subject_salts_of(uuid[])`: the existing salts, for the verifier; creates nothing.
   - `audit_erase_subject(uuid, uuid[])`: replaces 0014's one-argument version (below).
   Salts reach only this process's memory, for hashing. No API, viewer or export returns one.
4. **Canonical encoding, version 1** (implemented once, in `audit/domain/fingerprint.py`):
   - **Values** are the JSON values exactly as `field_changes` stores them (JSONB; the app
     writes them with `json.dumps`), written as canonical JSON with no whitespace:
     - `null`, `true`, `false`;
     - numbers by their decimal value: an integral value as its digits with an optional `-`
       (`1.0` → `1`, `-0` → `0`, `1e20` → `100000000000000000000`); any other value in plain
       decimal notation, no exponent, no trailing zeros, a digit before the point (`1.5e-7` →
       `0.00000015`, `-2.50` → `-2.5`). NaN and infinity are refused;
     - strings as JSON strings in UTF-8: `"` → `\"`, `\` → `\\`, U+0008 `\b`, U+000C `\f`,
       U+000A `\n`, U+000D `\r`, U+0009 `\t`, any other U+0000–U+001F as `\u00xx` (lowercase
       hex); everything else, U+007F and non-ASCII included, as its UTF-8 bytes;
     - arrays in order; objects with keys sorted by Unicode code point, written `"key":value`
       separated by `,`; keys must be strings.
     - Values that are not JSON yet (only direct callers pass them) are strings: an aware
       datetime as `YYYY-MM-DDTHH:MM:SS.ffffffZ` in UTC (a naive one is refused), a date as
       `YYYY-MM-DD`, a UUID lowercase with hyphens. A stored string is never reparsed.
   - **Field digest:** lowercase hex SHA-256 of `salt_1 ‖ … ‖ salt_n ‖ canonical value`, the
     salts being the field's subjects' salts in subject-ID order (IDs compared as lowercase
     strings). An ordinary field has no subjects: SHA-256 of the canonical value alone. A null
     value is digested as the bytes `null`.
   - **Change set:** the canonical JSON (same rules) of the object
     `{"record_id", "record_type", "saves", "v": 1}`, where `record_type` is the type history
     uses (`work_item` for all five work-item types, `asset`), and `saves` lists, in the
     entry's `fingerprint_saves` order, `{"change_id", "fields", "kind", "version"}` with the
     save's `kind` and `record_version` as stored, and `fields` = one array per stored history
     row `[field, digest(old), digest(new), [subject IDs]]` (subject IDs sorted; `[]` for an
     ordinary field), sorted by field, then by the rest of the array. A save that changed no
     field has its one stored row `["", digest(null), digest(null), []]`.
   - **Fingerprint:** `fp1:` + lowercase hex SHA-256 of the change set's bytes.
   - **Golden vector** (pinned by `app/modules/audit/tests/test_fingerprint.py`): record
     `0190a000-0000-7000-8000-000000000001` of type `work_item`; subjects
     `…-00000000000a` (salt bytes 0x00..0x0f) and `…-00000000000b` (0x10..0x1f); save
     `…-0000000000c1`, version 1, kind `created`: `subject` (personal) null →
     `Printer "P-3" jams\n`, `priority` null → `p2`, `custom.cost` null → `1.0`,
     `custom.ratio` null → `1.5e-7`; save `…-0000000000c2`, version 2, kind `updated`: `tags`
     `["a"]` → `["a","b"]`, `description` (personal) `قديم` →
     `{"z":1,"a":[true,false,null]}`, `technician_id` null →
     `0190a000-0000-7000-8000-0000000000ff`. The fingerprint is
     **`fp1:f27b292b6b9a3063d3ee32b318c7215b3aa4df90693a55d1dd3c230f7d1ea66d`**
     (`digest(null)` = `74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b`).
   A new layout gets a new prefix (`fp2:`); the verifier keeps verifying `fp1:`.
5. **The verifier** (scheduled and on-demand runs, `service/fingerprints.py`): for each
   fingerprinted entry in the range it reads the saves' rows back from `field_changes` (by
   history record type, record and change IDs: the existing tenant-first index), recomputes
   the fingerprint and says:
   - `verified`: every subject's salt is there and the fingerprint matches;
   - `erased_on_request`: a subject's salt is gone **and** an `audit.subject_erased` entry for
     that subject is dated after the entry (that entry is itself in the chain);
   - `mismatch`: otherwise (a changed or removed history row, a salt gone without a logged
     erasure).
   A run counts the three (`fingerprints_verified`, `fingerprints_erased`,
   `fingerprint_mismatches` on `audit_verification_runs`, in the API's run view). Any mismatch
   fails the run with problem `fingerprint_mismatch` and the first mismatching entry, after
   chain and anchor problems (which take precedence), and raises the usual alert. The entry
   view returns `fingerprint_status` (labels `audit_fingerprint_status.<code>`, en/ar/ur); the
   console mark is WP-064 S4.
6. **Erasure** (`erase_subject`, then `audit_erase_subject(subject, history_rows)`):
   - the service finds the entries listing the subject (`personal_subjects`, GIN index) and,
     from the lifecycle table, the personal-field rows of their saves;
   - the function deletes the subject's `audit_personal` rows (as before), blanks (SQL NULL)
     the given `field_changes` values, but only rows of saves whose entries list the subject
     (it checks `fingerprint_saves`, the record and `personal_subjects` itself), then destroys
     the salt: `salt` NULL and `erased_at` set, the row kept as a tombstone so the person never
     gets a fresh salt older entries would not match. It returns the counts, which the
     `audit.subject_erased` entry records (codes and counts only).
   - Everyone else's history and entries are untouched and still verify.
7. **Migration 0129** is expand-only. Its downgrade refuses, per tenant with `app.tenant_id`
   set, while any fingerprinted entry or salt exists (rule 5h), then restores 0014's function.

## Consequences

- A lifecycle save costs, in its own transaction, the digests (microseconds) and, when it
  changed a personal field, one resolver read and one definer call for the salts.
- Once a subject is erased, the entries using their salt are reported as erased on request as
  a whole: their ordinary fields are no longer recomputed either (the one fingerprint needs
  every salt). The definer limits which history rows can be blanked to those saves; which of
  their fields are personal comes from the app's lifecycle table.
- Saves made before 0129 have no fingerprint: their history is not covered, and erasure does
  not find it through entries (D-150: no back-filled entries). The people module's own
  anonymisation (REQ-ADM-101) still applies to them.
- Entries archived past retention (ADR-027 §8) are no longer in the live log; erasure finds
  only live entries, as it does for `audit_personal`.
- Rewriting history *and* the entries still needs the database owner, the anchor key and every
  anchor copy (ADR-027 Consequences); the fingerprint adds record history to what anchors and
  auditors' export copies protect.
