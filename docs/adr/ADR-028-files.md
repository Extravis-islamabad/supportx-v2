# ADR-028: Files — uploads stream through the API, per-tenant envelope encryption, scan before availability

- **Status:** Accepted
- **Date:** 2026-10-26
- **Source:** WP-022; architecture.md §6.8 (files), §11.3 (data protection); docs/specs/parity/01-work-items-incidents.md REQ-INC-079, REQ-INC-064; D-016, D-054, D-076, D-077, D-081
- **Owner:** Haider (Product Owner)

## Context

architecture.md §6.8 describes files as "direct-to-storage uploads with pre-signed URLs, antivirus
scanning (ClamAV) before availability, per-tenant encryption". REQ-INC-079 adds limits by type and
size, a visible scan state, browser previews and short-lived download links checked against the
user's access.

Pre-signed direct uploads put plain bytes into the bucket before the platform has seen them, so
neither the scanner nor per-tenant encryption can come first. The S3 features that would close the
gap are not deployment-neutral: SSE-KMS per tenant exists only on AWS, and SSE-C is unproven on
SeaweedFS, our on-prem store (D-016, ADR-012).

## Decision

1. **Uploads stream through the API** (D-081 D1). The browser sends the raw file body to
   `POST /api/v1/files`. The API checks the target's access, the type and size rules and the quota
   before storing anything. It then streams the body: it counts bytes (and aborts at the limit),
   sniffs the real type from the first bytes, hashes, and encrypts into an S3 multipart upload. The
   bucket only ever holds ciphertext, and no S3 URL is ever handed out. Downloads come back through
   the API too, from short-lived signed links.
2. **Per-tenant envelope encryption** (D-081 D2):
   - Each tenant has random 256-bit data keys, stored only wrapped (AES-256-GCM) by an
     **installation key**: `SUPPORTX_FILES_KEYS`, a Kubernetes secret on-prem; KMS behind the same
     port later.
   - Files are encrypted in 1 MiB AES-256-GCM chunks. The nonce is a per-file prefix plus the chunk
     counter. The associated data is the file ID, the counter and a last-chunk flag, so chunks
     cannot be reordered, swapped between files or cut off.
   - Fixed chunk offsets allow range reads (PDF previews) without decrypting whole files.
   - **Rotation:** a new installation key re-wraps the tenant keys, and old files stay readable by
     key ID. A new tenant key is used for new files.
   - **Crypto-shredding:** deleting a tenant's keys makes its files unreadable.
   - Losing the installation key loses every file, so backup and restore must include it
     (docs/architecture/files.md).
3. **Scan before availability** (D-081 D3). A worker decrypts each new file and streams it to
   clamd (`INSTREAM`):
   - only `clean` files can be previewed or downloaded;
   - `infected` files are blocked for good, and their object is deleted at once;
   - scanning is optional per installation, but `files.scan_required` is on by default, so files
     wait as "scanning";
   - when no scanner is installed, administrators see a warning that files are unscanned, never
     silence;
   - signatures older than 7 days raise an alert;
   - offline sites update signatures from a private mirror or an offline bundle.
4. **Images are processed in the worker** (D-081 D4):
   - Metadata (EXIF, including GPS; XMP; text chunks) is stripped losslessly from JPEG, PNG and
     WebP after a clean scan.
   - Pillow makes 320 px thumbnails under pixel and byte limits (decompression-bomb protection).
   - SVG and HTML are never rendered inline.
5. **Files are a shared platform service** (D-081 D5):
   - `app/shared/files` owns the tables (`files`, `file_links`, `tenant_data_keys`,
     `tenant_storage_usage`, `file_settings`) and the logic.
   - The `system` module (platform services, ADR-018) mounts its routes, scan consumer and
     schedules, because only modules are registered.
   - Who may see a file is answered by its owner module through a port (`FileOwnerAccess`).
     `work_items` answers for incidents, replies and notes, including private notes (staff only).
     Visibility is never copied onto the file, so making a note public takes its files along.
6. **Dangerous types are blocked by the real type** (D-081 addition):
   - A tenant-editable extension list blocks executables and scripts by default.
   - Each file's type is sniffed from its content, and a native executable, shebang script or
     Java archive is refused under any name when its family is on the list.

## Consequences

- Upload bandwidth goes through the API pods. Bodies are streamed, never held in memory, and
  bounded by the file size limit (25 MB default, at most 100 MB). A pre-signed path can be added
  behind the same API later if SSE-C proves reliable on SeaweedFS and AWS.
- One more installation secret to back up (the files key ring). Without it the API refuses to
  store files rather than storing plaintext.
- ClamAV needs about 1–1.5 GB of memory with signatures. It is an optional chart component, and
  its absence is visible.
- Owner modules provide a small access port. The files service never reads their tables.
