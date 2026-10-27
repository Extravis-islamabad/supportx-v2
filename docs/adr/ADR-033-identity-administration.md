# ADR-033: Identity administration through Keycloak's admin API

- **Status:** Accepted (WP-039; D-089, D-094)
- **Date:** 2026-10-27
- **Deciders:** Haider (Product Owner), lane B

## Context

Tenant admins must set up sign-in (single sign-on, sessions, later passwords and MFA) in
SupportX screens only (REQ-SEC-017); no tenant admin may get Keycloak console rights. Keycloak
keeps credentials and the login pages (ADR-006, D-009), and one realm serves every tenant, each a
Keycloak Organization (D-010). Keycloak 26.8 moved organization domain routing from identity
provider settings onto the organization's domains.

## Decision

1. **SupportX acts as one service account**, `supportx-identity` (client credentials only), with
   exactly the admin roles it needs: people, identity providers, organizations, reading login
   events. An upgrade step creates and repairs it on every deploy; it is never in the realm
   import file. The secret is an installation secret.
2. **Every call names its tenant and is checked**: an organization is found by its `tenant_id`
   attribute and confirmed by its alias (the tenant slug); identity providers are named
   `sx-<slug>-<random>`, linked to that organization, and SupportX only changes providers it has a
   row for in the tenant's own (RLS-protected) table.
3. **Single sign-on set-ups mirror Keycloak identity providers.** SupportX keeps the settings it
   shows (never the client secret); Keycloak keeps the secret, the certificates and the broker.
   Email domains are routed to the provider on the tenant's organization.
4. **Test before switching on, in a private window**: the test sign-in goes through the provider
   (`kc_idp_hint`), creates no SupportX session or person, and ends the tested Keycloak session.
   It cannot run in the admin's own browser: Keycloak refuses a second person there.
5. **SupportX enforces its own session limits** per tenant and app in the BFF; the realm's SSO
   session is raised to SupportX's longest so it never ends a session first.

## Consequences

- A tenant admin's mistake in a set-up cannot lock the tenant out: a set-up is hidden until it
  passed a test, and one that is on must be switched off before its connection changes.
- Keycloak changes are not in SupportX's database transaction: Keycloak is changed first and a
  failed row write undoes a provider just created.
- Before tenants share a realm (SaaS), email domains need a proof of ownership (D-094 open item).
- The service account can manage every realm user; tenant scoping is SupportX's job (item 2),
  covered by tests.
