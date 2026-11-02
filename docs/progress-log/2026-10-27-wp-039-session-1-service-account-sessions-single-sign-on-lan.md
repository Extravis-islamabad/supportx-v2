### 2026-10-27 — WP-039 session 1: service account, sessions, single sign-on (lane B)

- Built in `../supportx-v2-wp039` (branch `feat/wp-039-identity`), migration 0024 after lane
  A's 0023, D-094 and ADR-036 (numbers agreed with lane A).
- Proved on a throwaway Keycloak 26.8.1 before building: the least-privileged roles; that
  organization domain routing moved onto the organization's domains in 26.8 (the old
  `kc.org.*` provider settings are dropped); that Keycloak refuses a second person in a browser
  signed in as someone else (`different_user_authenticated`, after creating their account), so the
  test runs in a private window; that a SAML signature failure leaves no login event; that
  Keycloak answers `unauthorized_client` for both a right and a wrong secret, telling them apart
  only in its description; that undeclared user attributes are dropped (user profile).
- Checked end to end against that Keycloak with a second realm as the customer's provider, both
  OIDC and SAML, through the screens: wrong secret refused at the field, draft, test in a private
  window, switch on, a person of the domain sent straight to the provider and created in Demo
  Company with their department; a wrong SAML certificate fails and the set-up stays off.
- Pre-existing, not changed: the audit-integrity banner's link fails axe `link-in-text-block`
  when that banner shows (WP-018 banner); noted here for a fix.
