# ADR-046: Change-set fingerprints in lifecycle entries — two commitments to record history inside the entry hash (ordinary fields unsalted, personal fields salted), per-subject salts reachable only through definer functions, erasure that never hides a change to an ordinary value

- **Status:** Proposed (WP-064 S2)
- **Date:** 2026-11-11
- **Source:** WP-064; D-150 ("Values and verification", "Erasure"); ADR-027 §3, §5; ADR-045;
  coordinator 2026-11-11 (migration 0129, ADR-046, conditions 1 and 4; lane B's review: split
  the commitment so an erasure cannot hide tampering)
- **Owner:** Haider (Product Owner)

## Context

ADR-045 gives every save of a lifecycle record one chained audit entry naming its events. The
values themselves stay in record history (`field_changes`), which the app may only insert and
read but which anyone holding the database could still rewrite unnoticed. D-150 asks that the
entry hold a fingerprint of the save's change set, so record history becomes tamper-evident,
and that personal data be kept outside the chain behind a salted hash, so erasure stays
possible: after erasure the chain still verifies and shows "erased on request", accepted only
when a later `audit.subject_erased` entry exists.

A single salted fingerprint over the whole save is not enough. Once a subject's salt is gone,
nothing in that save can be recomputed, so its ordinary values (status, priority, group) lose
their tamper evidence too. **The attack:** someone who can trigger an erasure (an insider with
the app role, a compromised admin) first changes an ordinary history value in a save that lists
a subject, then erases that subject. With one fingerprint the verifier would report "erased on
request" instead of "mismatch". The erasure is audited, but the change to the ordinary value
would be hidden.

## Decision

1. **Two commitments, digests only, never values.** A lifecycle entry gains four columns,
   inside the entry hash only when set (so every entry written before 0129, and every non-save
   entry, hashes byte for byte as before):
   - `fingerprint`: commits to the save's **ordinary** fields (everything that is not personal),
     with **no salt**. It can always be recomputed from `field_changes`, before and after any
     erasure. It is present on every lifecycle entry from 0129 on.
   - `personal_fingerprint`: commits to the save's **personal** fields, salted with the data
     subjects' salts, so erasing a subject crypto-shreds these values in the chain. It is set
     only when one of the saves changed a personal field.
   - `fingerprint_saves`: the change IDs of the saves both cover, in save order (one entry can
     stand for several saves of one record in one request, ADR-045 §3).
   - `personal_subjects`: the user IDs whose salts the personal half uses (sorted; empty when no
     personal field changed or the record names nobody).

   **Why the ordinary fields stay outside the salt:** they must stay verifiable after an
   erasure. If they shared the personal salt, destroying it would make them unverifiable too,
   so an erasure could hide a change to them. Unsalted, a changed ordinary value is a mismatch
   whatever happens to the subjects. Ordinary values are codes, IDs, dates and numbers, never
   personal data, so leaving them unsalted reveals nothing that needs erasing.

   In the canonical entry content (ADR-027 §3) they appear as the keys `fingerprint`,
   `fingerprint_saves`, `personal_subjects` (when `fingerprint` is set) and
   `personal_fingerprint` (when it is set). Exports carry them inside the exported entry, so
   `tools/verify_export.py` checks them without change. It cannot recompute a fingerprint,
   because exports hold no record history; the live verifier does.
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
   recompute the personal half; per-field subjects would need a new layout (`fp2:`).
   The owning module tells the sink who the subjects are through a resolver it registers with
   `app/shared/history` (`register_subject_resolver`; work_items reads its row from the
   session's identity map, else one read under RLS), so audit reads no other module's table.
3. **Salts per data subject** (`audit_subject_salts`: tenant, subject, a random 16-byte salt,
   created, erased): RLS forced, tenant first in the primary key, and **no right at all for the
   app role**. Three SECURITY DEFINER functions, owned by the migrator with `search_path`
   pinned to `pg_catalog, public` and `EXECUTE` granted to `supportx_app` only (revoked from
   PUBLIC), are the only way in. FORCE RLS keeps each inside `app.tenant_id`:
   - `audit_subject_salts_ensure(uuid[], bytea[])`: get or create. The app passes a fresh
     `os.urandom(16)` per subject. An existing salt is never replaced. An erased subject gets
     no salt back, so a later save treats them as no subject. Refuses without a tenant.
   - `audit_subject_salts_of(uuid[])`: the existing salts, for the verifier; creates nothing.
   - `audit_erase_subject(uuid, uuid[])`: replaces 0014's one-argument version (§6).
   Salts reach only this process's memory, for hashing. No API, viewer or export returns one.
4. **Canonical encoding, version 1** (implemented once, in `audit/domain/fingerprint.py`):
   - **Values** are the JSON values exactly as `field_changes` stores them (JSONB; the app
     writes them with `json.dumps`), written as canonical JSON with no whitespace:
     - `null`, `true`, `false`;
     - numbers by their decimal value. An integral value is written as its digits with an
       optional `-` (`1.0` → `1`, `-0` → `0`, `1e20` → `100000000000000000000`). Any other
       value is written in plain decimal notation, with no exponent, no trailing zeros and a
       digit before the point (`1.5e-7` → `0.00000015`, `-2.50` → `-2.5`). NaN and infinity
       are refused;
     - strings as JSON strings in UTF-8: `"` → `\"`, `\` → `\\`, U+0008 `\b`, U+000C `\f`,
       U+000A `\n`, U+000D `\r`, U+0009 `\t`, any other U+0000–U+001F as `\u00xx` (lowercase
       hex). Everything else, U+007F and non-ASCII included, is written as its UTF-8 bytes;
     - arrays in order; objects with keys sorted by Unicode code point, written `"key":value`
       separated by `,`; keys must be strings;
     - values that are not JSON yet (only direct callers pass them) become strings: an aware
       datetime as `YYYY-MM-DDTHH:MM:SS.ffffffZ` in UTC (a naive one is refused), a date as
       `YYYY-MM-DD`, a UUID lowercase with hyphens. A stored string is never reparsed.
   - **Field digest:** lowercase hex SHA-256 of `salt_1 ‖ … ‖ salt_n ‖ canonical value`. An
     ordinary field has no salts: the digest is SHA-256 of the canonical value alone. A
     personal field uses the salts of every one of the entry's subjects, in subject-ID order
     (IDs compared as lowercase strings). A null value is digested as the bytes `null`.
   - **The two halves:** each is the canonical JSON (same rules) of the object
     `{"part", "record_id", "record_type", "saves", "v": 1}`:
     - `part` is `"ordinary"` or `"personal"`. It is inside the hashed bytes, so the two halves
       can never be swapped for each other;
     - `record_type` is the type history uses (`work_item` for all five work-item types,
       `asset`);
     - `saves` lists every save, in the entry's `fingerprint_saves` order, as
       `{"change_id", "fields", "kind", "version"}`, with the save's `kind` and
       `record_version` as stored. Every save is listed in both halves, even with no field of
       that part;
     - in the ordinary half, `fields` holds one array per stored history row whose field is
       not personal: `[field, digest(old), digest(new)]`;
     - in the personal half, `fields` holds one array per personal row:
       `[field, digest(old), digest(new), [subject IDs]]`, with the subject IDs sorted;
     - `fields` are sorted by their own canonical JSON bytes. A save that changed no field has
       one stored row, `["", digest(null), digest(null)]`, in the ordinary half.
   - **Fingerprints:** `fingerprint` = `fp1:` + lowercase hex SHA-256 of the ordinary half's
     bytes. `personal_fingerprint` = `fp1:` + the same over the personal half, only when at
     least one personal row exists.
   - **Golden vectors** (pinned by `app/modules/audit/tests/test_fingerprint.py`, and rebuilt
     there by hand with hashlib only). Both use record `0190a000-0000-7000-8000-000000000001`
     of type `work_item`. `digest(null)` is
     `74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b`.
     - **A, ordinary fields only:** save `…-0000000000c3`, version 4, kind `updated`:
       `priority` `p3` → `p2`, `custom.cost` null → `1.0`, `custom.ratio` null → `1.5e-7`,
       `tags` `["a"]` → `["a","b"]`.
       `fingerprint` = **`fp1:bb1da1530c996cd33f32d0ddcb06e5abee569db571995b72379a41b301a33e78`**;
       `personal_fingerprint` = none.
     - **B, ordinary and personal fields:** subjects `…-00000000000a` (salt bytes 0x00..0x0f)
       and `…-00000000000b` (0x10..0x1f).
       - Save `…-0000000000c1`, version 1, kind `created`: `subject` (personal) null →
         `Printer "P-3" jams\n`; `priority` null → `p2`.
       - Save `…-0000000000c2`, version 2, kind `updated`: `description` (personal) `قديم` →
         `{"z":1,"a":[true,false,null]}`; `technician_id` null →
         `0190a000-0000-7000-8000-0000000000ff`.
       - `fingerprint` = **`fp1:929257682249c7d55f6eebe8a2e94f6c22d53980a5de35d75c7c6e1aa8bc631a`**.
       - `personal_fingerprint` =
         **`fp1:6d5e5a7fe00b3fcd987413b14fbd4e2d62b7dd41d238b01e910aae2a8dcee4fc`**.
   A new layout gets a new prefix (`fp2:`); the verifier keeps verifying `fp1:`.
5. **The verifier** (scheduled and on-demand runs, `service/fingerprints.py`): for each
   fingerprinted entry in the range it reads the saves' rows back from `field_changes` (by
   history record type, record and change IDs, through the existing tenant-first index),
   recomputes both halves and gives one verdict:

   | Ordinary half | Personal half | Verdict |
   |---|---|---|
   | differs | anything (even with every subject erased) | `mismatch` |
   | matches | matches (or absent and still absent) | `verified` |
   | matches | every listed subject's salt present, but it differs, appeared or vanished | `mismatch` |
   | matches | a listed subject's salt is gone, and an `audit.subject_erased` entry for that subject is dated after the entry (itself in the chain) | `erased_on_request` |
   | matches | a listed subject's salt is gone without such an entry | `mismatch` |

   A run counts the three verdicts (`fingerprints_verified`, `fingerprints_erased`,
   `fingerprint_mismatches` on `audit_verification_runs`, in the API's run view). Any mismatch
   fails the run with problem `fingerprint_mismatch` and names the first mismatching entry.
   Chain and anchor problems take precedence. The run raises the usual alert. The entry view
   returns `fingerprint_status` (labels `audit_fingerprint_status.<code>`, en/ar/ur). The
   console mark is WP-064 S4.
6. **Erasure** (`erase_subject`, then `audit_erase_subject(subject, history_rows)`):
   - the service finds the entries listing the subject (`personal_subjects`, GIN index) and,
     from the lifecycle table, the personal-field rows of their saves; it passes only those;
   - the function:
     - deletes the subject's `audit_personal` rows, as before;
     - blanks (SQL NULL) the given `field_changes` values. It accepts only rows of saves whose
       entries list the subject: it checks `fingerprint_saves`, the record and
       `personal_subjects` itself;
     - then destroys the salt: `salt` NULL and `erased_at` set. The row is kept as a tombstone,
       so the person never gets a fresh salt that older entries would not match;
     - returns the counts, which the `audit.subject_erased` entry records (codes and counts
       only).
   - The function does not check which field a row holds, and it does not need to. Blanking
     an ordinary row changes the ordinary half, which has no salt, so the verifier reports a
     mismatch. Lane B chose this over passing field names to the definer.
   - Everyone else's history and entries are untouched and still verify.
7. **Migration 0129** is expand-only. Its downgrade refuses, per tenant with `app.tenant_id`
   set, while any fingerprinted entry or salt exists (rule 5h), then restores 0014's function.

## Tests that prove the rules

All in `backend/tests/db/test_audit_fingerprints.py` unless named otherwise:
- **The attack** (change an ordinary value, then erase the subject → still `mismatch`, and the
  run fails naming that entry): `test_an_ordinary_value_changed_before_an_erasure_is_still_a_mismatch`.
  The verdict rule alone is tested in `test_an_erasure_never_hides_a_changed_ordinary_value`
  (unit, `app/modules/audit/tests/test_fingerprint.py`).
- **An ordinary row blanked through the definer** → `mismatch`:
  `test_an_ordinary_row_blanked_through_the_definer_is_a_mismatch`.
- **Erasure with untouched ordinary fields** → `erased_on_request`, while other subjects'
  saves still verify: `test_erasure_shows_erased_on_request_and_everyone_else_still_verifies`.
- **A save without personal fields** has no `personal_fingerprint` and verifies:
  `test_a_save_without_free_text_uses_no_salt`.
- **The golden vectors**, rebuilt by hand: `test_golden_vectors`,
  `test_golden_vector_a_recomputed_by_hand`, `test_golden_vector_b_recomputed_by_hand` (unit).

## Consequences

- A lifecycle save costs, in its own transaction, the digests (microseconds) and, when it
  changed a personal field, one resolver read and one definer call for the salts.
- After an erasure, the subject's personal values are gone and so is their salt. Every
  ordinary value of the same saves stays fully verifiable, so an erasure never hides a change
  to them.
- Saves made before 0129 have no fingerprint: their history is not covered, and erasure does
  not find it through entries (D-150: no back-filled entries). The people module's own
  anonymisation (REQ-ADM-101) still applies to them.
- Entries archived past retention (ADR-027 §8) are no longer in the live log. Erasure finds
  only live entries, as it does for `audit_personal`.
- Rewriting both the history and the entries still needs the database owner, the anchor key
  and every anchor copy (ADR-027 Consequences). The fingerprints add record history to what
  the anchors and the auditors' export copies protect.
