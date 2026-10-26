# Files and safe attachments

How SupportX stores, scans, encrypts and serves files (WP-022). Decisions: ADR-028 and D-082.
Requirement: REQ-INC-079, plus REQ-INC-064 AC2 for inline images.

## Shape

| Part | Where |
|---|---|
| Rules, no I/O: real-type sniffing and blocking, names, states, chunked encryption format, link tokens, metadata stripping | `backend/app/shared/files/domain/` |
| Installation key ring (wraps tenant data keys) | `backend/app/shared/files/keyring.py` |
| Tables, encrypted blobs, scanner adapters (clamd, none, fake), Pillow thumbnails | `backend/app/shared/files/infra/` |
| Operations: upload, scan, access, cleanup, admin | `backend/app/shared/files/service/` |
| Who may see, attach or remove (owner modules answer) | `ports.py`; for work items: `app/modules/work_items/service/file_access.py` |
| HTTP routes, scan consumer, schedules, realtime, quota, usage counter | the `system` module (`api/files.py`, `service/files.py`) |

Files are a platform service (architecture.md §6.8, D-082 D5): the code lives in `app/shared`,
which owns the tables. Only modules can be registered, so the `system` module mounts it.
Event types are therefore `system.file.*`. Owner modules never share their tables: they answer
`FileOwnerAccess` questions, and the files service never reads their rows.

## Tables (migration 0018, all with tenant RLS)

| Table | Holds |
|---|---|
| `files` | Name, size, SHA-256, sniffed type and kind, scan state and signature, object and thumbnail keys, the data key used, source |
| `file_links` | Where the file is attached: work item, conversation entry or editor draft. Also the record, for listing and purging. Exactly one per file |
| `tenant_data_keys` | The tenant's data keys, wrapped by the installation key ring |
| `tenant_storage_usage` | Bytes and files counted against the `storage_gb` limit |
| `file_settings` | Size limit, batch size, blocked extensions (versioned) |

## Upload (ADR-028 item 1)

`POST /api/v1/files?owner_type=…&owner_id=…&name=…[&inline=true]` takes the raw file body (no
multipart). It runs these steps in order:

1. **Owner:** the owner module checks access. A draft belongs to its uploader only.
2. **Declared size** (`Content-Length`) against the limit: refused before any byte is read.
3. **Quota** against the declared size.
4. **First 8 KB:** sniff the real type and check it against the blocked list.
5. **Stream:** encrypt into object storage, cut off at the limit.
6. **One transaction:** the quota again (row lock), the file, its link, usage, and the event
   `system.file.uploaded`. If it fails, the stored object is removed.

An `Idempotency-Key` replays the same file. Several files mean one request each; the console
sends at most three at a time.

**Memory and connections:** steps 1–3 run in a short transaction of their own, and step 5 holds
no database connection, so slow uploads never exhaust the pool. At most
`SUPPORTX_FILES_UPLOAD_CONCURRENCY` uploads (default 8) per API process write at once; the rest
wait with their bodies unread. Each writing upload holds about one 5 MiB S3 part plus its
encryption. Load check (`tests/db/test_files_load.py`, opt-in): 50 parallel 25 MB uploads, all
stored, 57 MB/s on a laptop, Python peak 389 MB with both ends of the requests in one process.

**Blocking (D-082):**

- Default blocked extensions: executables and scripts (`exe msi bat cmd com scr pif cpl dll sys
  msc ps1 psm1 vbs vbe js jse wsf wsh hta sh bash zsh csh ksh command jar apk app lnk reg`). The
  list is the tenant's to edit.
- Content checks catch renamed files: Windows PE, ELF and Mach-O binaries count as `exe`, a
  shebang as `sh`, and a ZIP with a Java manifest as `jar`. Each is refused under any name while
  its family is on the list.
- SVG and HTML are stored but never rendered inline.

## Encryption (ADR-028 item 2, D-082 D2)

- **Format:** objects are `header | chunks`. Each chunk is 1 MiB of AES-256-GCM, with the nonce
  being the per-file prefix plus the chunk counter. The associated data is the file ID, the
  counter and a last-chunk flag (`domain/chunks.py`). Reordering, cross-file swaps and
  truncation all fail to decrypt.
- **Range reads:** the content route decrypts only the chunks a range touches (PDF viewers).
- **Tenant keys:** each tenant has random data keys, stored only wrapped by the installation key
  ring `SUPPORTX_FILES_KEYS` (`<id>:<base64 32 bytes>, …`, active key first). The ring is bound
  to the tenant ID, so a key moved to another tenant does not open.
- **No ring, no files:** without the ring the API answers 503 `files_not_configured`. It never
  stores plaintext.

### Backup and restore (required: losing the key ring loses every file)

The bucket and the database alone cannot be read back without the key ring. Back up, together:

1. the PostgreSQL database (CloudNativePG backups, D-038). It holds `tenant_data_keys`;
2. the object storage bucket (SeaweedFS or S3) under `tenants/`;
3. the Kubernetes Secret `supportx-app`, key **`files-keys`**: the key ring. On Compose dev
   stacks the ring is derived from `SESSION_SECRET` in `deploy/compose/.env`.

To restore:

1. Put the Secret back **before** the API and workers start. A ring missing a key that wrapped a
   data key makes those files fail to open, with an error naming the missing key.
2. Restore the database and the bucket from the same point in time.
3. Check: `kubectl -n supportx exec deploy/supportx-api -- python -m tooling.files_keys check`
   lists every tenant as ok (a missing key is named, exit code 1). Then open one old file in the
   console and confirm Admin > Files shows no warnings.

Keep the key ring in at least two places: the cluster's secret backup and an offline copy (the
installer's escrow, WP-014c). Treat it like the database superuser password.

### Rotation

| Rotate | How | Effect |
|---|---|---|
| Every tenant's data key | `python -m tooling.files_keys rotate` | New files use the new key; old files keep theirs |
| The installation key | 1. Put a new key **first** in `files-keys` and keep the old one after it. 2. Roll the API and workers. 3. Run `python -m tooling.files_keys rewrap`. 4. Remove the old key from the ring | Stored data keys move to the new installation key; file objects are never rewritten |

Download-link signatures derive from the active key, so links issued before a rotation stop
working (they live minutes).

## Scanning (ADR-028 item 3, D-082 D3)

1. The `system__file_scan` consumer (and `system__files_scan_sweep` every 5 minutes) decrypts
   each waiting file and streams it to clamd (`INSTREAM`).
2. The verdict decides what happens:

| Verdict | Result |
|---|---|
| **clean** | Images get metadata stripped and a thumbnail (below); the file becomes `clean` |
| **infected** | `infected` for good. The object is deleted at once; the row keeps name, hash and signature. Audit entry `file.blocked`; metric `supportx_files_blocked` |
| **scanner or storage down** | The attempt is counted and the file keeps waiting. After 3 attempts it is `scan_failed` ("could not be checked"); administrators can rescan |
| **ciphertext unreadable** | `scan_failed`, logged as an error |

**No scanner installed:**

- With `files.scan_required` on (the default), files wait as "scanning". Admin > Files and the
  scanner check (hourly, metric `supportx_files_scanner_problems{problem}`) say so.
- With it off (an operator's knowing choice), files are `not_scanned`: they open, carry their
  state everywhere, and administrators are warned.

**Signatures** older than 7 days raise `signatures_stale` (Admin > Files, metric, error log).
Offline sites update them from a private mirror, or load the offline bundle (below).

The scanner streams each file to clamd in pieces (`INSTREAM`); the worker never holds a whole
file for scanning. Only images up to 50 MB are read whole, for metadata stripping and thumbnails.

### ClamAV in the chart

`clamav.enabled` (on in every profile) runs one `supportx-clamav` StatefulSet:

- clamd and a freshclam sidecar, both as UID 1000 with the chart's own `clamd.conf` and
  `freshclam.conf` (the image's start script needs root);
- an init container that fetches signatures before clamd starts, into a PVC (`clamav.storage`);
- a network policy that admits only the API and the consumers, on port 3310.

`files.scanRequired` (default true) becomes `SUPPORTX_FILES_SCAN_REQUIRED`, and the clamd address
is wired to the API and workers automatically.

Signature updates, by site type:

| Site | How |
|---|---|
| Internet access | freshclam updates from `database.clamav.net` every few hours |
| Private mirror | `clamav.privateMirror: http://mirror.internal/clamav` |
| Air-gapped | `deploy/scripts/clamav-signatures.sh fetch <dir>` on a connected machine, carry `<dir>` in, then `deploy/scripts/clamav-signatures.sh load <dir> [namespace]`. clamd reloads within 10 minutes. Repeat at least weekly, or the 7-day alert fires |

## Images (ADR-028 item 4, D-082 D4)

After a clean scan, in the worker:

- **Metadata** is stripped losslessly (`domain/metadata.py`):
  - JPEG: EXIF/XMP (APP1), IPTC (APP13) and comments go. The orientation stays, in a minimal
    EXIF block;
  - PNG: text and EXIF chunks go;
  - WebP: EXIF and XMP chunks go.

  The cleaned bytes are re-encrypted and replace the original.
- **Thumbnail** with Pillow (`infra/thumbnails.py`), protected against decompression bombs:
  - inputs over 50 MB are not decoded;
  - the header is checked first: images over 40 megapixels are refused before any pixel is read;
  - Pillow's own bomb warning is an error;
  - JPEGs are decoded at reduced scale; only the first frame is used.

  The result is a 320 px WebP with no metadata.

## Access and links (REQ-INC-079 AC3, AC4)

**Who sees a file.** The owner module decides:

- an incident's own files: anyone who may view the incident;
- a reply's or note's files: whoever sees the entry. A **private** note's files are for people
  who may see private notes (`add_note`); everyone else gets 404;
- nothing is copied onto the file, so making a note public takes its files along.

**Routes:**

| Route | Use |
|---|---|
| `GET /files/records/{type}/{id}` | Everything on a record the caller may see |
| `POST /files/{id}/link` | A link valid 5 minutes, bound to the user. The content route checks the HMAC, the expiry (410 `file_link_expired`), the user, then access again. Only `clean` files open, or `not_scanned` while scanning is not required |
| `GET /files/{id}/inline`, `/thumbnail` | Images for the editor and the list (session cookie, same checks) |

Content responses always carry:

- `X-Content-Type-Options: nosniff`;
- `Content-Security-Policy: sandbox`;
- an RFC 6266 `Content-Disposition` (UTF-8 names). Only images and PDFs may be `inline`; others
  download as `application/octet-stream`.

Opening a private note's file is an audited read (`file.downloaded`); public files are not
audited (D-082 D7).

## Deletion and purge

| What | How |
|---|---|
| `DELETE /files/{id}` | Hidden at once (audited `file.deleted`); the object goes after 24 hours (`system__files_purge`, hourly; audit `file.purged`) |
| Editor drafts never attached | Removed after 24 hours |
| A purged record (`purge_record`, called by the record purge, WI-020 AC3) | Takes its files along (D-077) |

Usage always drops in the same transaction as the removal.

## Quota (D-082 D6)

- **Limit:** the licence limit `storage_gb`. Placeholders: Essentials 50, Professional 250,
  Enterprise 1,000.
- **Counting:** uploads compare bytes; the licence summary shows whole GB used, rounded up.
- **Over the limit:** 403 `storage_quota_exceeded`, with the used and limit numbers.

## Settings and status (`files.manage`)

| Route | What |
|---|---|
| `GET` / `PUT /files/settings/rules` | Max size 1–100 MB (default 25), batch 1–50 (default 20), blocked extensions. If-Match; every change audited with old and new values |
| `GET /files/settings/usage` | Bytes, files, limit |
| `GET /files/settings/status` | Scanner installed and reachable, signature date, counts waiting, failed and not scanned, and `warnings[]` (labelled `file_warning.*`) |
