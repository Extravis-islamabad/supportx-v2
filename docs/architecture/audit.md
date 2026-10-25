# Audit log (WP-018)

The tamper-evident audit log of architecture.md §7.4: who did what, when, from where, and proof
that nothing was changed, removed or inserted afterwards. Decisions: ADR-027, D-076. Module:
`backend/app/modules/audit`. This page is for engineers adding audited actions and for operators.

## What gets recorded

- **Privileged writes:** every route that changes roles, access, organisation, configuration,
  record actions (delete, restore, due date) and the audit settings themselves. A route says so
  with a dependency; an architecture test fails if a privileged route has none.

  ```python
  note: Annotated[AuditNote, audited("role.updated", object_type="role", object_param="role_id")]
  note.details = {"grants_added": [...], "grants_removed": [...]}
  ```

- **Sensitive reads** (REQ-AUD-004): `audit_read(ReadCategory.X)` logs a read at most once per
  person, object and read window (10 minutes by default). Reading the audit log is always logged.
- **Refusals** (REQ-AUD-005): 401, 403, 404-for-hidden, licence and read-only refusals are
  logged by an error observer in `app/core/errors.py`; 10 refusals in 10 minutes by the same
  person raise a probing alert.
- **Sign-in, sign-out and tenant switch** from the BFF (`record_alone`). Keycloak's own events
  (failed sign-ins, MFA) come with WP-039.

Every action is a stable code in `domain/catalogue.py` with labels `audit.action.<code>` in
English, Arabic and Urdu. To add one: add it to the catalogue, add the labels, mark the route.

## How it is protected

1. **Record:** the entry is written in the request's own transaction (it exists exactly when
   the change does) and queued. The app role may INSERT and SELECT audit rows, never UPDATE or
   DELETE (the grants are the guarantee, not the code).
2. **Seal:** `audit_seal()`, a SECURITY DEFINER function owned by the migrator, takes queued
   entries in time order under a per-tenant advisory lock and writes the chain link:
   `SHA-256("sx-audit-v1" ‖ tenant ‖ seq ‖ previous chain hash ‖ entry hash)`. The app cannot
   write chain rows. The sealing consumer runs within seconds; the screen shows "Pending seal"
   until then, and the seal sweep alerts if an entry waits longer than 5 minutes.
3. **Anchor:** the worker signs the newest chain position with the installation's Ed25519 key
   (`SUPPORTX_AUDIT_SIGNING_KEY`, a Kubernetes secret) at most hourly. An anchor proves that the
   newest entries were not cut off. Rotated keys stay trusted for old anchors through
   `SUPPORTX_AUDIT_TRUSTED_KEYS`. An HSM or KMS signer can replace the local key later (the
   `AnchorSigner` protocol).
4. **Verify:** daily for the previous day and weekly for the whole chain (from the retention
   cut-off), and on demand. A run recomputes every entry hash, chain link, personal-data
   commitment and anchor. The first problem is named by position and kind (`audit.problem.*`).
   A failure writes an audit entry, raises `audit.alert.raised`, adds to the
   `supportx_audit_verification_failures` metric and shows the console banner until a later full
   run passes. The notification engine (WP-023) will deliver the alert as well.

**Personal data** (IP address, user agent, free-text reason) is kept outside the hash in
`audit_personal`, one salted row per person. The entry holds only a commitment to it. Erasing a
person deletes their rows; the chain still verifies (REQ-AUD-013).

**Separation of duties:** the built-in Auditor role reads, searches, exports and verifies, and
changes nothing. Tenant administrators change the settings (each change is audited with old and
new values). Nobody, admins included, can change or delete an entry: there is no such route,
and a route-table test keeps it that way. Without `audit.view` the audit routes answer 404.

## Exports and the offline verifier

An auditor asks for a time range (optionally filtered) as JSON lines or CSV. The consumers
worker builds a zip in object storage (kept 7 days) with:

| File | Contents |
|---|---|
| `manifest.json` | range, first and last position, previous chain hash, anchors, trusted keys, the server's own verification result, SHA-256 of the data file |
| `manifest.sig` | Ed25519 signature of the manifest |
| `audit.jsonl` / `audit.csv` | the entries in chain order with their hashes and personal data |
| `verify_export.py` | the verifier: Python 3.10+, standard library only |
| `README.txt` | how to verify, including the openssl commands for the signatures |

`python3 verify_export.py export.zip` exits 0 with "verified N entries (complete)" or 1 with the
first problem. An unfiltered export also proves that no position is missing.

## Retention (mixed approach, D-076 item 10)

The default retention is 3 years. An admin can set 1 to 10 years. Once a day, `audit__retention`:

1. writes each whole month past retention to `audit/archive/<tenant>/<yyyy-mm>.zip` (the export
   format, without personal data, which is not kept past retention);
2. reads the archive back and verifies it (hash and full offline verification);
3. records it in `audit_archives` and calls `audit_advance_cutoff()`. This moves the tenant's
   cut-off (`audit_cutoffs`): the select policies of `audit_entries` and `audit_personal` hide
   older rows from every app query, and the personal rows are deleted. The function refuses a
   cut-off inside one year or without a ready archive behind it;
4. calls `audit_drop_expired_partitions()`, which drops a monthly partition once every tenant's
   cut-off is past it (the migrator reads across tenants for this only, through
   `*_maintenance_select` policies allowlisted in `tooling/rls_guard.py`).

An archive covers a contiguous run of chain positions, so the archives and the live chain
together remain one verifiable chain. Verification and exports start after the last archived
position.

**Never silent:** if storage is missing or unreachable, entries are unsealed, the positions are
out of order, or the archive does not verify after it is read back, the job records a failed
archive row with a reason, writes an audit entry, raises the `archive_failed` alert (banner),
increments `supportx_audit_archive_failures` and logs an error. Nothing is hidden in that case.
The job retries the next day.

**Restore for investigation:** Admin › Audit log › Archives › Restore copies an archive back
into `audit_restored` after verifying it again. It is readable for 7 days, outside the live log.
Restoring is audited.

## Storage

The S3 API only (`app/shared/storage`, aioboto3), with `SUPPORTX_OBJECT_STORAGE_*` settings:
SeaweedFS in the Helm chart's dev and single-node profiles, any S3-compatible service elsewhere,
MinIO in the dev Compose stack. WP-022 (attachments) reuses the same component.

## Volume

`tests/db/test_audit_scale.py` loads N entries, seals them, verifies the whole chain, runs the
screen's search and detects a changed entry. It runs with 100,000 entries on every CI run and
with 10,000,000 nightly (`.github/workflows/audit-scale.yml`), with timings in the job summary.
Entry lookups are bounded by the chain's times, so PostgreSQL reads only the monthly partitions
involved.

## Operations

| Signal | Meaning | Action |
|---|---|---|
| Banner "An entry was changed…" / `supportx_audit_verification_failures` | verification found a problem | open Integrity, note the position, preserve the database, investigate |
| `unsealed_overdue` | the consumers worker is down or stuck | check the worker and NATS |
| `archive_failed` | a month could not be archived | check object storage; the job retries daily |
| `audit_anchoring_off` (log) | no signing key configured | set `SUPPORTX_AUDIT_SIGNING_KEY` (`deploy/scripts/secrets.sh` creates one) |
