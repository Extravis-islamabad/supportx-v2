# Authentication: how logging in works

SupportX never handles passwords. **Keycloak** does all authentication (local accounts, LDAP/AD,
SAML, OIDC, MFA). The SupportX API contains a small **backend-for-frontend (BFF)** that talks to
Keycloak on the browser's behalf (architecture.md §11.1, D-009). The browser only ever holds one
opaque, HttpOnly session cookie: **no token ever reaches JavaScript**.

## The login flow

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser (console / portal)
    participant A as SupportX API (BFF)
    participant V as Valkey (sessions)
    participant K as Keycloak (realm "supportx")
    participant D as PostgreSQL

    B->>A: GET /api/v1/auth/me
    A-->>B: 401 (no session)
    B->>A: GET /api/v1/auth/login?app=console&returnTo=/tickets
    A->>V: store one-time state (PKCE verifier, nonce, returnTo) - 10 min
    A-->>B: 302 to Keycloak /auth (code_challenge, state, nonce)
    B->>K: username, then password (identity-first login)
    K-->>B: 302 to /api/v1/auth/callback?code&state
    B->>A: GET /api/v1/auth/callback
    A->>V: take state (deleted: single use)
    A->>K: POST /token (code + PKCE verifier + client secret)  [back channel]
    K-->>A: ID, access and refresh tokens
    A->>A: verify ID token (RS256 signature, issuer, audience, expiry, nonce)
    A->>D: read tenant(s); create/update the user (just-in-time)
    A->>V: new session record (encrypted, AES-256-GCM)
    A-->>B: 302 to /tickets + Set-Cookie: supportx_session (HttpOnly, SameSite=Lax)
    B->>A: GET /api/v1/auth/me (cookie)
    A-->>B: user, tenant, tenants, csrf_token
```

In words:

1. The app asks `/auth/me`. Without a session it sends the browser to `/auth/login`.
2. The BFF creates a one-time *state* (with a PKCE verifier and a nonce), keeps it server-side, and
   redirects the browser to Keycloak.
3. The user signs in **on Keycloak's page** (SupportX never sees the password).
4. Keycloak sends the browser back to `/auth/callback` with a one-time *code*.
5. The BFF exchanges the code for tokens **server-to-server** (proving the PKCE verifier and its
   client secret), checks the ID token's signature and claims, and works out the tenant.
6. It creates or updates the user's row in that tenant, stores a **new** session, sets the cookie
   and sends the browser back to the page it started on.

`returnTo` only accepts same-origin relative paths (`/tickets?id=7`). Anything else (`https://…`,
`//evil`, backslash tricks, encoded variants) lands on `/`, so the login can never be used as an
open redirect.

## Where things live

| Item | Where | Notes |
|---|---|---|
| Password, MFA | Keycloak only | Password policy (12+ chars, upper, lower, digit, special, not username/email, history 3) and brute-force lockout (5 failures) are on in every environment. |
| ID / access / refresh tokens | Valkey, inside the session record | Encrypted with AES-256-GCM (key from `SUPPORTX_SESSION_SECRET`, D-021). Never sent to the browser. |
| Session ID | Browser cookie `supportx_session` (`__Host-supportx_session` in production) | Random, opaque, HttpOnly, SameSite=Lax, Secure except plain-http local dev. Valkey keys are the SHA-256 of it. |
| CSRF token | Inside the session; given to the app by `/auth/me` | Held in memory by the app, sent as `X-CSRF-Token`. |
| User profile | `users` table, per tenant | Created/updated on every login (just-in-time provisioning). |

### Session lifetime

- **Idle timeout** (`SUPPORTX_SESSION_IDLE_TIMEOUT_SECONDS`, default 30 min) and **absolute
  timeout** (`SUPPORTX_SESSION_ABSOLUTE_TIMEOUT_SECONDS`, default 12 h): whichever comes first.
- **Every login creates a new session ID** (an old cookie, including one planted by an attacker, is
  discarded): no session fixation. Switching tenant also issues a new ID.
- **Silent refresh**: when the access token expires the BFF refreshes it server-side. If Keycloak
  refuses (user logged out, disabled, or removed from the organization), the session ends at once.
  If Keycloak is merely unreachable, the session continues until its own timeouts.
- **Logout** (`POST /auth/logout`) deletes the session and ends the Keycloak SSO session from the
  back channel, so the next visit asks for credentials again.

### CSRF: why the synchronizer-token pattern

Every POST/PUT/PATCH/DELETE that relies on the cookie must carry `X-CSRF-Token` equal to the token
stored **in the server-side session** (and, when the browser sends `Origin`, it must be the console
or portal). GET stays read-only. We chose this over the double-submit cookie because:

- the token never needs to live in a JavaScript-readable cookie;
- a cookie injected by a sibling subdomain cannot forge it (double-submit compares a cookie with a
  header, both of which such an attacker could set);
- it changes automatically with the session (login, tenant switch).

`SameSite=Lax` on the session cookie is a second layer.

## How the tenant is chosen

Tenants are **Keycloak Organizations** in one shared realm (ADR-006 revised, D-010). Each
organization has a `tenant_id` attribute holding the SupportX tenant UUID. The `console` and
`portal` clients add a `supportx_organizations` claim (`alias → {tenant_id, id}`) to the ID token
(requested with the `organization:*` scope).

- **One organization** → that tenant.
- **Several** → all are listed in the session; the first (by alias) is active. `POST
  /api/v1/auth/switch-tenant` moves to another one under a new session ID.
- **None** → `403 no_organization`, and the Keycloak session is ended. A browser is sent back to the
  app, which shows a translated message.
- The tenant must also exist and be active in SupportX (`tenants` table), otherwise
  `403 tenant_not_provisioned`.

Every API request then takes its tenant **and user** from the session: the BFF puts them into the
database transaction (`app.tenant_id`, `app.user_id`), where row-level security enforces the tenant
and a trigger stamps `created_by` / `updated_by` (see `tenancy.md`).

The old `X-Tenant-ID` header is **off by default everywhere**. It can be switched on only for local
development with `SUPPORTX_DEV_TENANT_HEADER=true`, works only in the dev and test profiles, only
when there is no session, and is **always ignored in production**, whatever the settings say.

## Adding an SSO provider (e.g. Microsoft Entra ID) later

No SupportX code changes are needed; it is Keycloak configuration:

1. In Entra ID, register an application (redirect URI:
   `https://<keycloak>/realms/supportx/broker/entra/endpoint`) and create a client secret.
2. In Keycloak (realm `supportx`) → **Identity providers** → add **Microsoft** (or generic OpenID
   Connect) with alias `entra`, the client ID and secret, and the tenant's issuer.
3. **Organizations** → the customer's organization → **Identity providers** → link `entra` and set
   the email domain (e.g. `customer.com`) with *redirect when email domain matches*. Users of that
   domain are then sent to Entra ID automatically on the identity-first login page.
4. Add mappers if needed (e.g. name, email, `locale`). Users who sign in this way become members of
   the organization, so they land in the right SupportX tenant on their first login (just-in-time).
5. For customers who need a fully separate configuration, the dedicated-realm option of ADR-006
   remains available.

## Failure behaviour

| Situation | API answer | Browser sees |
|---|---|---|
| No / unknown session | `401 unauthenticated` | Redirected to sign in |
| Idle or absolute timeout, refused refresh | `401 session_expired` | Redirected to sign in |
| Missing or wrong CSRF token, foreign Origin | `403 csrf_failed` | Translated error |
| No organization / tenant not set up / user disabled | `403 no_organization` / `tenant_not_provisioned` / `user_disabled` | App page with translated message and "Sign in again" |
| Keycloak unreachable at login | `503 identity_provider_unavailable` | Translated error; `/api/v1/ready` reports `keycloak: failed` |

Errors are RFC 9457 problem details with a machine `code`; nothing internal (stack traces, token
contents) is ever returned.
