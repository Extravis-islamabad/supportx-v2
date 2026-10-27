# Identity: sign-in settings and single sign-on

WP-039 (REQ-SEC-007, 008, 013, 017, 029, 031), ADR-036, D-089, D-094. Session 1 of 3: the
Keycloak service account, sessions per tenant, people creation, single sign-on. Passwords,
invitations, resets and mail come in session 2; MFA and "my account" in session 3.

Admins use **Admin › Sign-in and security** (`identity.manage`). Nothing is set in Keycloak's
console by hand.

## Pieces

| Piece | Where | Notes |
|---|---|---|
| Service account | `supportx-identity` client, made by `tooling/keycloak_identity.py` | Client credentials only; `manage-users`, `manage-identity-providers`, `manage-organizations`, `view-events`. Chart Job `keycloak-identity` per revision; `make keycloak-identity` on the Compose stack. Also turns login events on (7 days), raises the realm's SSO session to SupportX's longest, declares `sx_department` / `sx_site` in the user profile |
| Admin API client | `identity_access/infra/keycloak_admin.py` | Organizations found by their `tenant_id` attribute, confirmed by alias |
| Settings | `identity_settings` (RLS) | Session idle and absolute limits per app; people creation on first sign-in |
| Set-ups | `sso_providers` (RLS) | Mirror of a Keycloak identity provider (`sx-<slug>-<random>`), never the client secret |
| Test sign-ins | Valkey, encrypted, 15 minutes | `service/sso_test.py` |
| API | `/api/v1/identity/settings`, `/api/v1/identity/sso…` | Every write audited (`identity.settings_changed`, `sso.*`) |
| Live | list channel `identity` | Other admins' screens refetch on `identity_access.identity_settings.changed` and `.sso_provider.changed` |

## Sessions (REQ-SEC-029, REQ-SEC-031)

- Defaults and caps (Appendix A): console 60 minutes idle, 12 hours absolute, at most 7 days;
  portal 30 minutes idle, 12 hours absolute, at most 30 days; idle 5 minutes to 24 hours.
- A session takes its tenant's limits when it begins (sign-in, tenant switch); a change applies
  to sessions begun afterwards.
- Keycloak's SSO session is at least SupportX's longest, so SupportX decides. After a SupportX
  session timed out, the next sign-in asks for the password again (`prompt=login`): Keycloak's
  own session never signs the browser back in silently.
- Deactivating a person ends their sessions in the tenant (the "ended at" marker, WP-021) and
  closes their live connection at once. Their Keycloak sessions stay, because one Keycloak user
  serves all of a person's tenants; signing in again here is refused.

## Single sign-on (REQ-SEC-007, REQ-SEC-008)

Life cycle: **draft → tested → on ⇄ off**, removable at any time.

1. **Add.** Microsoft Entra ID, Okta, Google, any OpenID Connect provider, or SAML 2.0.
   - OpenID Connect: SupportX reads the issuer's discovery document; its issuer must be the one
     typed. With a secret, it asks the provider whether it accepts the client (only
     `invalid_client`, or Keycloak's "Invalid client credentials", means no).
   - SAML: metadata uploaded or fetched from its address, read by Keycloak's import endpoint;
     or the sign-in address and certificate by hand. The certificate must be valid now.
   - The provider is created hidden, linked to the tenant's organization, with its mappers
     (email, names, department, site). Its email domains become the organization's domains,
     routed to it. Public mail domains are refused; a domain another organization has is refused
     by Keycloak; two set-ups of a tenant never share one.
   - Fetches follow the request-forgery rules of `infra/fetch.py`: no link-local (cloud metadata),
     multicast, reserved or unspecified addresses, loopback only with
     `SUPPORTX_SSO_FETCH_ALLOW_LOOPBACK=true` (dev and CI), no redirects, 5 seconds, 1 MB.
2. **Test**, in a private window. The admin copies the link; the private window goes straight
   to the provider (`kc_idp_hint`), lands on `/sso-test-done` (no session needed), and the admin's
   screen shows who signed in and what came for department and site. No SupportX session and no
   person are created; the tested Keycloak session ends at once. In the admin's own browser
   Keycloak refuses (`different_user_authenticated`): it never switches people in one session.
   A refusal Keycloak records is shown in plain words; a SAML signature that does not match is
   not recorded, so after a minute the screen says the other window's error is the reason.
3. **Switch on.** Shown on the tenant's sign-in page. If chosen, people whose email is in its
   domains go straight to it (`autoRedirect` on the domains, only while on). A first sign-in
   creates the person (if people creation is on) with the department and site the provider sent,
   matched by code or name.
4. **Change.** Changing how SupportX connects sends the set-up back to draft (test again); an
   "on" set-up must be switched off first. The client secret is write-only: leave it empty to
   keep it.
5. **Remove.** The Keycloak provider is deleted and the domains only it added are given back.

### Security notes

- The service account can manage every user of the realm: tenant scoping is SupportX's (ADR-036
  item 2), tested in `tests/db/test_identity_api.py`.
- Existing Keycloak accounts are linked only through Keycloak's default flow (confirm, then
  prove the account). Automatic linking is never configured: in a shared realm one tenant's
  provider could otherwise sign in as another tenant's user.
- **Multi-tenant installations** (`SUPPORTX_MULTI_TENANT=true`, chart `multiTenant`) route only
  email domains the organization has verified; others are refused (`sso_domain_unverified`, D-098).
  The DNS TXT proof that verifies them comes with the SaaS cell (WP-014d). Single-tenant
  installations are unaffected.

## Scope for workers (D-052)

`identity_access.subject_for(session, tenant_id, user_id)` gives code without the app (the
consumers worker: exports, scheduled reports) the user's compiled subject, read from the
database now: the API's own compile (same catalogue, roles, memberships, entitlements), so a
worker decides exactly as the API would. A deactivated or deleted user gets the subject that may
do nothing. Tested against the API's compile in `tests/db/test_subject_for.py`.

## Operators

- New installation or upgrade: nothing to do; the chart's Job sets up the service account.
- If the bootstrap admin was replaced, the Job says so and exits 0. Create the client by hand
  once: confidential, service accounts only, the secret `keycloak-identity-secret`, and the four
  `realm-management` roles above; then turn on login events and declare `sx_department` and
  `sx_site` in the user profile (admins view and edit).
- Compose dev stack: `make dev-init` (adds `KEYCLOAK_IDENTITY_CLIENT_SECRET`), `make
  keycloak-identity`, `make backend-env`.
