# ADR-027: Audit log — record then seal, a per-tenant hash chain built in the database, signed anchors, personal data outside the hash

- **Status:** Accepted
- **Date:** 2026-10-24
- **Source:** WP-018; architecture.md §7.3, §7.4, §11.2, §11.3; docs/specs/parity/11-admin-users-security-audit.md (REQ-AUD-001 to 013); D-034, D-058, D-076
- **Owner:** Haider (Product Owner)

## Context

architecture.md §7.4 asks for a separate, append-only audit log of security-relevant actions,
protected by a hash chain so that changing or removing entries is detectable, and exportable for
compliance. Field history (WP-012, D-034) records record changes but is not that log. The log
must also hold refused attempts (which roll back), sensitive reads, and personal data that a
later erasure must remove without breaking the chain.

## Decision

1. **Record, then seal** (D-076 item 1). A request writes its entry in its own transaction (an
   entry exists exactly when the change committed) and queues it. A sealer gives queued entries
   consecutive positions in the tenant's chain shortly afterwards. No per-tenant lock is held by
   requests, and refused attempts can be written after their transaction rolled back. Entries
   waiting to be sealed show as "pending seal"; one waiting longer than 5 minutes raises an alert.
2. **The database builds the chain.** `audit_seal()` is a SECURITY DEFINER function owned by the
   migrator: it takes a per-tenant advisory lock and computes
   `chain_hash = SHA-256("sx-audit-v1" ‖ tenant ‖ seq ‖ previous chain hash ‖ entry hash)`.
   The application role can call it but has no INSERT, UPDATE or DELETE on `audit_chain`, and
   no UPDATE or DELETE on entries. FORCE ROW LEVEL SECURITY keeps the function inside the
   caller's tenant. This replaces the plan's separate `supportx_audit` login role: one less
   credential to deploy, and chain values cannot be forged by application code.
3. **Canonical entry hash.** `entry_hash = SHA-256(canonical JSON of the entry)`: sorted keys,
   no whitespace, UTF-8, no floats, times as UTC with microseconds. The same bytes are produced
   by the service, the database function and a standalone offline verifier; golden tests pin
   them.
4. **Signed anchors** (D-076 item 2). Each tenant's newest position is signed at most hourly with
   an Ed25519 installation key (`cryptography`, D-021), held in a Kubernetes secret mounted only
   into the consumers worker. Anchors detect removal of the newest entries and a rewritten
   chain. Verifiers trust only configured public keys (the active key and retired keys listed in
   `SUPPORTX_AUDIT_TRUSTED_KEYS`), never a key found in the database, so checkpoints signed by
   old keys stay verifiable after rotation. **Later:** an `AnchorSigner` backed by an HSM or a
   cloud KMS replaces the in-memory key without changing the anchor format.
5. **Personal data outside the hash** (D-076 item 3). IP addresses, user agents and free-text
   reasons are stored per data subject in `audit_personal` with a random salt; the entry holds
   only `SHA-256(salt ‖ canonical(data))` per subject. People appear in entries by user ID only;
   names are looked up when read. Erasure deletes the subject's personal rows through the
   definer function `audit_erase_subject()`; the chain and everyone else's commitments still
   verify, and the person's entries still group under the same ID.
6. **Coverage is enforced.** Privileged routes declare `audited(action, ...)`; sensitive reads
   declare `audit_read(category)`; refused and failed attempts at audited routes are written by
   an error observer registered with core. An architecture test fails for any administrative
   write route without `audited`, and for any route that could change or delete an entry.
7. **Separation of duties** (D-076 item 6). A built-in Auditor role reads, searches, exports and
   verifies and changes nothing; settings need `audit.manage`; every settings change is itself
   audited. Without `audit.view` the audit API answers 404.
8. **Storage.** `audit_entries` is partitioned by month (partitions created ahead by a definer
   function on a daily schedule); retention defaults to 3 years (1 to 10). Rows past a tenant's
   retention are archived to S3-compatible object storage, then hidden by an RLS cut-off; a
   monthly partition is dropped only when every tenant in it has expired (D-076 item 10).
   Details fixed in session 3:
   - An archive is one whole month and covers a contiguous run of chain positions, so the
     archives and the live chain remain one verifiable chain; verification and exports start
     after the last archived position.
   - It is read back and verified before `audit_advance_cutoff()` moves the cut-off. That
     migrator-owned function refuses a cut-off inside one year or without a ready archive.
   - Archives hold no personal data: it is deleted at the cut-off, so it is not kept past
     retention, and erasure requests never have to touch archives.
   - Positions follow sealing order, not occurrence order. A month whose positions run more than
     a day past its end fails visibly (`audit_archive_out_of_order`) instead of archiving live
     entries.
   - The partition clean-up reads across tenants through `*_maintenance_select` policies for
     the migrator only (allowlisted in the RLS guard).
   - An archive can be restored for an investigation into `audit_restored` (verified again,
     kept 7 days, outside the live chain).
9. **Periodic work** runs as module schedules in the consumers worker (`ModuleSpec.schedules`),
   one runner per schedule across replicas through an advisory lock: sealing sweep, anchoring,
   daily and weekly verification, partitions, retention, restored-copy expiry. Temporal (WP-025) is for durable business timers.

## Consequences

- Admin actions cost one extra INSERT (plus a personal row and an outbox row) in their own
  transaction; everyday record work is not audited and pays nothing.
- Someone holding the database owner role, the anchor key and every anchor copy could still
  rewrite history; anchor copies outside the installation and the export files auditors keep are
  the defence, as for any hash-chained log.
- Keycloak-side events (failed sign-ins, MFA, password resets) are added by WP-039 (D-076 item 7).
- Until the notification engine exists (WP-023), alerts are an audit entry, a console banner, an
  `audit.alert.raised` event and a Prometheus metric (D-076 item 8).
