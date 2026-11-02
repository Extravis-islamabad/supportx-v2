# API keys

An API key lets a program call the SupportX API without a browser. Every key belongs to an owner
and acts as that owner, limited to the scopes it was given (D-128).

## Getting a key

- **Administrators** (permission "Manage API keys") make keys for **service identities**, the
  accounts integrations act as, so an integration keeps working when the person who set it up
  leaves. They also see and can revoke every key of the organisation.
- **People** can make keys for themselves only when an administrator allows it (Admin > Security,
  "People may make API keys for themselves"; off by default).
- The key is shown **once**, when it is made. Afterwards only its name and its last four characters
  are shown. Store it in your secret manager straight away. If it is lost, revoke it and make a new
  one: SupportX cannot show it again, because it never stores it.

## Using a key

Send it in the `Authorization` header:

```http
GET /api/v1/incidents HTTP/1.1
Host: supportx.example.com
Authorization: Bearer sxk_…
```

A key needs no cookie and no CSRF token. Every call checks, in this order: that the key exists
and is genuine, that it is not revoked or expired, that the call comes from an allowed address,
and that its owner is still active. Then the call needs **both** a scope that covers it and the
owner's own permission at that moment: a key never does more than its owner may, and when the
owner loses a permission, the key loses it on its next call.

Keys never reach the browser-only routes: signing in, the session, a person's own profile, and
making, listing or revoking keys.

## Scopes

Scopes are `<area>:read` and `<area>:write`, one pair for each area of the permission catalogue
(`incidents:read`, `incidents:write`, `knowledge:read`, `users:read` and so on). `read` covers
viewing, searching and exporting; `write` covers everything else in the area. The list of scopes
of your installation: `GET /api/v1/api-keys/scopes` (in a signed-in browser session).

A call without the scope it needs gets:

```json
{ "status": 403, "code": "api_scope_missing", "params": { "scope": "incidents:write" } }
```

## Expiry, addresses, revocation

- **Expiry:** 90 days by default, at most one year ahead. A key without an expiry date can only be
  made when an administrator allows it.
- **Allowed addresses:** optionally up to 20 addresses or networks (`203.0.113.7`, `10.0.0.0/8`).
  A call from anywhere else is refused (403 `api_key_ip_refused`) and written to the audit log.
- **Revocation** takes effect at once: the key's next call is refused (401 `api_key_revoked`).
- Other refusals: 401 `api_key_invalid` (not a key, or not this organisation's), `api_key_expired`,
  `api_key_owner_inactive`.

## Finding leaked keys

SupportX keys have a fixed, public shape, so secret scanners can find them in code, logs and
tickets. Add this pattern to your scanner (for example as a custom gitleaks or GitHub secret
scanning rule):

```
sxk_[0-9a-hjkmnp-tv-z]{26}_[0-9a-hjkmnp-tv-z]{26}_[A-Za-z0-9_-]{43}
```

A key is `sxk_`, the organisation's ID, the key's ID and a 43-character random secret. If a key
leaks, revoke it at once in Admin > API keys (or My account > API keys for your own).
