# ADR-050: Field encryption — one key-provider interface, tenant data keys reused from files, ADR-048 blobs bound to the record and field

- **Status:** Proposed (WP-057 S3a, lane C, 2026-11-13). Shape approved by the coordinator;
  approved in principle by lane B with the conditions now written in (2026-11-13).
- **Deciders:** Haider (Product Owner), through the coordinator; lane B reviews (blocking, D-149)
- **Related:** D-161 (field encryption reuses the files key ring), ADR-048 (key ring and sealed-blob
  format), ADR-028 (files: tenant data keys wrapped by the installation key), D-021 (PyCA
  `cryptography`), rule 5f (no deployment-mode branches), REQ-SEC-040, REQ-INC-019 (server-side
  drafts), #406 (webhook header values)

## Context

Some values must not sit readable in the database or its backups even for someone who can read
the tables:
- secrets that are typed into settings (webhook header values in workflow definitions, which #406
  masks on every read but stores in plain text);
- whole drafts of records that may hold personal data (REQ-INC-019's server drafts);
- later, fields an admin marks as sensitive (REQ-SEC-040).

D-161 decided the shape: per-tenant data keys wrapped by an installation key, the files key ring's
model, reached through one key-provider interface, with customer-managed keys as a later
implementation of the same interface. ADR-048 decided the blob format: a key ID in every blob,
HKDF per purpose, and associated data that binds the blob to what it belongs to. What is left is
how the two fit together, and what the modules call.

## Decision

1. **The key provider** is the only thing that touches the installation key. Its *Protocol*
   lives in `app/shared/crypto/provider.py` (crypto stays a leaf: the codec and this Protocol,
   importing nothing of files or fields); its implementations live in `app/shared/fields/`:

   ```python
   class KeyProvider(Protocol):
       active_kek_id: str
       def wrap(self, tenant_id: UUID, data_key: bytes) -> tuple[str, bytes]: ...
       def unwrap(self, tenant_id: UUID, kek_id: str, wrapped: bytes) -> bytes: ...
   ```

   The implementation now is the installation ring, `SUPPORTX_FILES_KEYS`, through the files
   `KeyRing` (ADR-028). It is a Kubernetes Secret on-prem and air-gapped, and a cloud KMS synced
   by External Secrets Operator on SaaS: the same setting in every profile, so there is no
   deployment-mode branch anywhere (rule 5f). A customer's own KMS or HSM is another class with the
   same three members, chosen by configuration; it is not built now (D-161 item 3).

2. **The data keys are the tenant's existing ones** (`tenant_data_keys`, created on first use,
   ADR-028). No new table, no migration. A field key is never a file key: files encrypt chunks with
   the data key itself, while a field uses HKDF(data key, `supportx/field.<purpose>/v2`) through
   ADR-048's codec, so the two uses can never share an AES key or a nonce space.

3. **The blob is ADR-048 v2**, with:
   - **key ID** = the data key's ID as 32 lowercase hex characters (a UUID without dashes, which
     fits ADR-048's `^[a-z0-9_-]{1,32}$`). The reader finds the data key from the blob alone, and
     a retired data key still opens what it sealed;
   - **purpose** = `field.<module>.<what>`, for example `field.automation.webhook_header` or
     `field.work_items.draft`. Purposes are constants in the owning module, checked against
     ADR-048's pattern;
   - **bound_to** = (tenant ID, table, record ID, field name). A blob copied to another record,
     another field or another tenant fails as a bad tag. Where the record does not exist yet (a
     draft), the caller binds to the ID it is about to use;
   - **text form** = `sx2:` + base64url, for text and JSONB columns.

4. **What modules call** (`app/shared/fields/`, a new shared package importing crypto's codec and
   files' data keys through two narrow calls, `current_data_key` and `data_key`):

   ```python
   cipher = await field_cipher(session)   # the session's tenant (app.tenant_id), the provider
   text = await cipher.seal(purpose, bound_to, value)      # str -> "sx2:..."
   value = await cipher.open(purpose, bound_to, text)      # -> str | None
   ```

   - `seal` uses the tenant's newest data key, and refuses a `bound_to` with an empty or missing
     part. `open` uses the data key the blob names.
   - **What `open` does when it cannot open**, by cause:
     - **the data** is wrong (a bad tag, a malformed blob, a data key ID this tenant does not
       have): it returns None. A caller shows such a value as unreadable, never as empty and
       never as an error page;
     - **the installation key** cannot unwrap the data key (a missing or wrong Secret: operations,
       not data): it raises, and the API answers 503 `field_keys_unavailable`, so good data is
       never marked unreadable because of a configuration fault.
   - **A None from `open` is a security event, never silent.** It is logged as
     `field_unreadable` with the purpose, the data key ID and the reason class (unknown key,
     bad tag, malformed) only, never the value, the blob or the bound record's content. It is
     counted in a metric labelled by purpose and reason, and an alert fires on any bad tag,
     since that means someone changed stored data.
   - Unwrapped data keys are cached per process for 5 minutes, keyed by (tenant, data key ID), in
     a bounded LRU (about 1,000 keys), in memory only: never logged, pickled or put in Valkey. A
     data key's unwrapped value never changes for its ID, so rotation needs no invalidation.
   - **Tenant erasure empties the cache at once in every process:** the erasure step writes a
     `fields.tenant_keys_destroyed` event to the outbox, and every API and worker process drops
     that tenant's keys when it arrives, so crypto-shredding never waits for a cache to expire.
     A test proves `open` fails right after erasure.
   - **Purposes** are constants in the owning module; a guard test refuses a purpose used by two
     modules. A value bound to an ID not yet inserted (a draft) must be inserted with exactly that
     ID (tested).
   - Modules never see a data key or the provider. Import-linter contracts: `app.shared.crypto`
     imports neither `app.shared.files` nor `app.shared.fields` (no cycle: files already imports
     crypto), and modules import `app.shared.fields` only through its package root.

5. **Rotation**, as D-161 item 4:
   - **A new installation key** is a configuration change: list the new key first. Files'
     `rewrap_data_keys` re-wraps each tenant's data keys under it. Field values are not
     rewritten, because they name a data key, not the installation key.
   - **A new data key** for a tenant (`rotate_data_key`) seals new values; old values keep
     opening with theirs. Re-sealing old values is a background job, added when the first purpose
     needs it.

6. **Refusing to lose data** (ADR-048 item 5) comes in S3b: a key user that counts the data keys
   still wrapped under each installation key, so the API refuses to start when a key that still
   wraps something is removed from `SUPPORTX_FILES_KEYS`. The count crosses tenants under forced
   RLS, so it needs a narrow SECURITY DEFINER function returning only a number. That migration is
   S3b's. Until then, files' existing behaviour stands: an unlisted key fails when its data is
   read.

7. **Erasing a tenant** destroys its data keys (crypto-shredding, as with files, ADR-028). Every
   field sealed for that tenant, in the database and in every backup, becomes unreadable at the
   same moment as its files, because only the destroyed data keys open them. Nothing has to find
   or rewrite those values. Erasing one person (GDPR) does not use this: a person's sealed fields
   are deleted or blanked by the erasure job like their other fields, because the tenant's data
   keys are shared by everyone in it.

## Why reuse files' data keys instead of a second set

- One per-tenant key set means one rotation story, one backup item and one crypto-shredding step
  (D-161's rationale).
- HKDF per purpose (ADR-048) already gives each use its own AES key from the same secret, so
  sharing the data key costs no separation.
- It needs no migration, so lane A's drafts and #406's headers are not held by a migration turn.

## Why the record and field are in the associated data

Encryption alone stops someone reading the database. Binding stops someone with write access
moving a value: copying a webhook secret from one workflow into another that they control, or
swapping two people's sensitive fields. Both would decrypt without binding; with it they fail.

## Consequences

- `SUPPORTX_FILES_KEYS` becomes the installation key for files and fields. Its documentation,
  backup guide and secrets.sh text say so. Losing it loses both, as it already loses every file.
- Searching or sorting on an encrypted field is impossible. Purposes are chosen for values nobody
  searches (secrets, drafts). REQ-SEC-040's admin-marked fields will need a separate decision on
  blind indexes if search is wanted.
- One extra small query per request that opens a field, cached for 5 minutes per data key.
- A data key unwrap failure (the installation key is missing) is loud: `open` logs a
  `field_key_unavailable` warning with the key IDs only, and the readiness check reports it.

## Alternatives considered

- **A separate field key table:** a second key set to rotate, back up and shred, for no gain in
  separation over HKDF per purpose.
- **Encrypting directly under the installation key:** a new installation key would mean
  rewriting every field value, and there would be no per-tenant crypto-shredding.
- **PostgreSQL pgcrypto:** the key would travel to the database in every statement and appear in
  its logs and `pg_stat_statements`. The keys must stay in the application (D-021).
