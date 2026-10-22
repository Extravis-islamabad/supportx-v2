# ADR-006: Identity provider: Keycloak, bundled

- **Status:** Accepted
- **Date:** 2026-10-22
- **Source:** architecture.md §4.1, §5, §11.1
- **Owner:** TBC

## Context

Authentication must cover local users, LDAP/AD, SAML, OIDC (Entra ID, Okta, Google), MFA and password policies, and must work air-gapped.

## Decision

Bundle Keycloak for all authentication. One realm per tenant in SaaS. The browser uses OIDC Code + PKCE through a backend-for-frontend; tokens stay server-side and the browser holds an HttpOnly session cookie. Building in-house was rejected.

## Consequences

- **Positive:** Standards-complete and self-hostable.
- **Negative:** Realm-per-tenant at large SaaS scale needs validation (Keycloak performance with many realms).
- **Negative:** Authorisation (RBAC + ABAC) stays in SupportX's own policy layer, not in Keycloak.

## Notes

Accepted at bootstrap (architecture.md §19 listed it as *Proposed*); confirm owner at Stage 0 sign-off.
