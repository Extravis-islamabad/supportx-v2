# Rotating the sign-in key (admin guide)

SupportX keeps each signed-in session on the server, encrypted with the installation's
**sign-in key**. The key can be changed without signing anyone out: SupportX keeps a short list
of keys, the **key ring**. The newest key encrypts every session saved from then on, and every
key on the list can still read sessions saved before. This guide is for the people who run the
installation (D-162, ADR-048).

## What users see

Nothing. Nobody is signed out, and nobody has to sign in again. Each session moves to the new
key by itself the next time it is saved (any request a minute or more after the last one does
it).

## The settings

| Setting | What it is |
|---|---|
| `SUPPORTX_SESSION_KEYS` | The key ring, as JSON, **newest first**: `[{"id": "2026-11", "secret": "..."}, {"id": "legacy"}]`. A key ID is 1 to 32 of `a-z`, `0-9`, `_` and `-`; a date such as `2026-11` works well. Each secret is at least 32 characters in production; use random hex (`openssl rand -hex 32`). |
| `SUPPORTX_SESSION_SECRET` | The single key from before. Alone, it is a ring of one key called `legacy`. With `SUPPORTX_SESSION_KEYS` set, list `{"id": "legacy"}` (no secret: it is this one) for as long as sessions saved under it must still be read. It also stays the key behind API keys, list paging and custom-domain proofs (see the upgrade notes). |
| `SUPPORTX_DOMAIN_PROOF_SECRET` | Optional: the key behind custom-domain verification. Not set: `SUPPORTX_SESSION_SECRET`, as before. |

With the Helm chart, put each secret in the `supportx-app` Secret under its own key, and list
the IDs in the values; the chart never holds a secret itself:

```yaml
secrets:
  sessionKeys:
    - {id: "2026-11", key: session-key-2026-11}   # newest first
    - {id: legacy}                                 # session-secret, during the overlap
```

## Rotating

1. **Make the new secret** and store it with the installation's other secrets (on Kubernetes:
   `kubectl -n supportx patch secret supportx-app --type merge -p '{"stringData":
   {"session-key-2026-11": "'"$(openssl rand -hex 32)"'"}}'`). Back it up like the others.
2. **List it first**, keeping the current key after it:
   `[{"id": "2026-11", "secret": "..."}, {"id": "legacy"}]` (or, for a later rotation,
   `[{"id": "2027-05", ...}, {"id": "2026-11", ...}]`).
3. **Restart the API and the workers** (with Helm: upgrade the release). Every replica must run
   with the same list.
4. **Wait out the overlap**: keep the old key listed for **at least the absolute session
   lifetime**. That is 12 hours by default, but an organisation may set longer sessions in its
   own sign-in settings (up to 7 days on the console and 30 days on the portal): wait for the
   longest one any organisation uses. After that no live session still needs the old key.
5. **Retire the old key**: remove it from the list and restart again. Then destroy its secret.

The audit log of every organisation records each step as the system: **A new sign-in key was
put into use** (with the key ID, the key it follows and how many keys are still accepted) and
**A sign-in key was retired**. Key material is never logged or audited. Each step is recorded
once, however many replicas start at the same time.

If you remove a key too early, sessions saved under it end: those people sign in again. Nothing
else is lost.

## Checks

- `/api/v1/ready` reports **Sign-in keys** as a warning (never as not ready) when more than three
  keys are listed: old keys are probably never retired.
- A key that stored data still needs cannot be removed: the API refuses to start with
  `session_key_still_in_use` and the key ID. List the key again. (Sessions never block a
  removal; this protects data that later features encrypt with the same kind of key.)
- A malformed `SUPPORTX_SESSION_KEYS` stops the start-up with a message naming the problem and
  the key ID, never a secret.

## Upgrade notes (from a single SUPPORTX_SESSION_SECRET)

- Nothing changes until you set `SUPPORTX_SESSION_KEYS`: the existing secret is the ring `legacy`
  and every session stays signed in. Sessions saved before the upgrade stay readable while
  `legacy` is listed.
- **Keep `SUPPORTX_SESSION_SECRET` set** even after `legacy` leaves the ring. API keys are hashed
  under a key derived from it, and list paging and domain proofs use it too. Removing it would
  silently end every API key, so production **refuses to start** with `SUPPORTX_SESSION_KEYS`
  but no `SUPPORTX_SESSION_SECRET`, unless `SUPPORTX_API_KEY_SECRET`, `SUPPORTX_CURSOR_SECRET`
  and `SUPPORTX_DOMAIN_PROOF_SECRET` are all set. Setting a new `SUPPORTX_API_KEY_SECRET` ends
  every existing API key: their owners must make new ones.
- Rotating the sign-in key never changes API keys, list paging or domain proofs.
