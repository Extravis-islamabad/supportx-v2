# ADR-048: Key ring and sealed-blob format — key IDs in every blob, HKDF per purpose, a ring that opens with any listed key, a "who still uses key X" hook

- **Status:** Proposed (D-162, lane B, 2026-11-12)
- **Deciders:** Haider (Product Owner), through the coordinator
- **Related:** D-021 (BFF session encryption), D-162 (rotatable sign-in key), D-161 and WP-057
  (field encryption, lane C), ADR-028 (files key ring), migration 0146

## Context

The BFF's session records in Valkey were sealed with one AES-256-GCM key,
sha256("supportx/bff-session/v1" + SUPPORTX_SESSION_SECRET), and the blob carried no key ID
(D-021). The key could not be changed without ending every session, and the same secret also fed
the list-cursor key, the API-key hash key and the custom-domain proof. D-162 asks for a rotatable
sign-in key: the newest key seals, every listed key stays readable for an overlap (no mass
sign-out), each rotation is audited, and rotating never breaks the secret's other users. Lane C's
field encryption (WP-057) needs the same things, so the format is decided once here.

## Decision

1. **Codec and ring are separate.** `app/shared/crypto/codec.py` is pure (no I/O, no settings):
   - `KeyMaterial(id: str, secret: bytes)`; the secret never appears in a repr;
   - `seal(key, purpose, bound_to, plaintext) -> bytes`;
   - `open_sealed(lookup, purpose, bound_to, blob) -> bytes | None`, where `lookup(key_id)`
     returns the secret or None. None for an unknown key, a bad tag or a malformed blob; a
     malformed `purpose` or `bound_to` is the caller's mistake and raises ValueError;
   - `to_text` / `from_text`: the text form `"sx2:" + base64url` without padding, for text
     columns and JSON.

   `app/shared/crypto/ring.py`: `KeyRing`, keys newest first, never empty, unique IDs. The newest
   seals; any listed key opens. It is no more than one `lookup` plus "which is newest". Where keys
   come from is the owner's business (the session ring is built from settings by identity_access).
2. **Per-use key:** HKDF-SHA256(ikm = secret, salt = None, info = b"supportx/" + purpose +
   b"/v2"), 32 bytes. Purposes match `^[a-z0-9_./-]{1,64}$`.
3. **Blob v2:** `0x02 | len(key_id) (1 byte) | key_id (ASCII) | 12-byte random nonce |
   AES-256-GCM ciphertext + 16-byte tag`. Key IDs match `^[a-z0-9_-]{1,32}$`, else ValueError.
4. **Associated data:** b"supportx/" + purpose + b"/v2\x00" + key_id + b"\x00" + bound_to_bytes,
   where bound_to_bytes is the parts (UTF-8) joined by b"\x00". `bound_to` needs at least one
   part (an empty sequence raises ValueError in `seal` and `open_sealed`: every blob is bound to
   something), and every part must be non-empty and contain no NUL, else ValueError, so
   ("a", "bc") and ("ab", "c") never collide. A single string is refused as `bound_to` (it would
   be read as its characters).
5. **The users hook** (`app/shared/crypto/users.py`): modules register, per ring,
   `async (key_id) -> int`, the number of their stored items that still need a key. At start-up
   the ring's owner asks for every key it recorded before but no longer lists; any count above 0
   refuses to start with `<ring>_key_still_in_use` (for sessions `session_key_still_in_use`) and
   the key ID. With nothing registered it never refuses. Sessions register nothing: they expire,
   so the overlap is enough. WP-057 registers its count of data keys still wrapped under a key.
6. **The session ring** (D-162): `SUPPORTX_SESSION_KEYS`, JSON, `[{"id", "secret"}, ...]` newest
   first; `SUPPORTX_SESSION_SECRET` alone is the one-key ring `legacy`. With both, the ring is
   `SUPPORTX_SESSION_KEYS`, which may list `{"id": "legacy"}` (its secret is then
   `SUPPORTX_SESSION_SECRET`). Purpose `bff-session`, `bound_to` = [the Valkey store key], as the
   old associated data. Every save re-seals under the newest key. Every ring key except `legacy`
   has a secret of at least 32 bytes (UTF-8), in every profile: the settings refuse a shorter
   one, and so does the ring builder (`session_ring`) for any other caller. `legacy` is the
   secret from before D-162 and is accepted as it was (production still asks 32 characters of
   `SUPPORTX_SESSION_SECRET`).
7. **v1 compatibility:** a blob without the 0x02 header (or one whose random first byte happens to
   be 0x02 but does not open as v2) is tried with the old derivation, only while `legacy` is
   listed, read-only. Nothing is ever written as v1 again.
8. **Recording and audit** (migration 0146):
   - `session_key_ids` (platform table: key ID, first seen, retired; IDs only, RLS forced, the
     app may select, insert and update, never delete);
   - `session_key_events` (platform table): each claimed change, waiting to be announced;
   - `session_key_announcements` (tenant table, RLS, unique per tenant and change, select and
     insert only): which changes are already in that tenant's audit log.

   API start-up only **claims**: a new ID is inserted with ON CONFLICT DO NOTHING ... RETURNING
   and a missing one retired with UPDATE ... WHERE retired_at IS NULL RETURNING; only the
   replica whose statement returned the row adds the change to `session_key_events`, in the same
   transaction. Start-up never writes a tenant's audit log, so many tenants never slow or fail
   it. The very first start only records the ring: that is no rotation.

   The audit log is per tenant (ADR-027) and there is no platform audit log yet (a follow-up in
   PROGRESS.md), so the schedule `identity_access__session_key_announce` (consumers worker)
   writes each change into every tenant's log, as the system: `security.session_key_rotated`
   (new key, previous newest, number of readable keys) or `security.session_key_retired`. Per
   tenant, in one transaction with app.tenant_id set, it inserts the tenant's announcement row
   (ON CONFLICT DO NOTHING RETURNING) and writes the entry only when that row was returned, so
   entry and marker commit together: a crash neither loses nor repeats an entry, and two runs at
   once write one. Tenants created after a change are not told about it. Once every tenant has
   it, the change is marked announced and no longer looked at.
9. **The secret's other users are untangled:** the cursor key and the API-key hash key fall back
   only to `SUPPORTX_SESSION_SECRET`, never to the ring, with their old derivations byte for byte;
   domain proofs take `SUPPORTX_DOMAIN_PROOF_SECRET`, else `SUPPORTX_SESSION_SECRET` as before.
   Production refuses `SUPPORTX_SESSION_KEYS` without `SUPPORTX_SESSION_SECRET` unless the
   API-key, cursor and domain-proof secrets are set.

## Why HKDF per purpose

One ring may serve several uses (sessions now; WP-057 may reuse the format with its own ring). A
per-purpose key means two uses never encrypt under the same AES key, so a blob of one purpose can
never be opened, or have its nonce space shared, by another, even with the same ring secret.
HKDF is the standard extract-and-expand KDF for this (RFC 5869), in PyCA `cryptography`
(already approved, D-021). The purpose is also in the associated data, so a wrong purpose fails as
a bad tag in any case.

## Why the key ID in the blob and in the associated data

The ID tells the reader which key to try, so the ring opens without trial decryption, and
binding it in the associated data means editing the header to name another listed key fails the
tag. A short, operator-chosen text ID (a date such as `2026-11`) keeps the blob small and the
audit entries readable.

## Consequences

- Rotation is a configuration change and a restart: list the new key first, keep the old one for
  at least the absolute session lifetime, then remove it. Nobody is signed out.
- Field encryption (WP-057, lane C) reuses the codec and registers a key user; D-161's key
  provider supplies its ring. Its blobs carry the same header and text form.
- A key removed while a registered user still needs it stops the API from starting: a loud
  failure instead of unreadable data.
- `/ready` warns (informational) above three listed keys.

## Alternatives considered

- **Trying every key without an ID** (as D-021 would have to): costs one decryption per key per
  request and cannot tell "unknown key" from "tampered".
- **Re-encrypting every session at rotation:** a sweep over Valkey for data that expires anyway.
- **Reusing the files key ring (ADR-028) for sessions:** its keys are 32 random bytes in a
  different format and wrap tenant data keys; mixing the uses would tie session rotation to the
  files re-wrap. The blob format here is the one to converge on.
