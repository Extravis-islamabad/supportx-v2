# ADR-006: Identity provider: Keycloak, bundled

- **Status:** Accepted
- **Date:** 2026-10-22
- **Source:** architecture.md §4.1, §5, §11.1
- **Owner:** Haider (Product Owner)

## Context

Authentication must cover local users, LDAP/AD, SAML, OIDC (Entra ID, Okta, Google), MFA and password policies, and must work air-gapped.

## Decision

Bundle Keycloak for all authentication. ~~One realm per tenant in SaaS.~~ (superseded — see revision below). The browser uses OIDC Code + PKCE through a backend-for-frontend; tokens stay server-side and the browser holds an HttpOnly session cookie. Building in-house was rejected.

## Consequences

- **Positive:** Standards-complete and self-hostable.
- **Negative:** Tenant-to-organization mapping must be kept in sync with the `organization` module; tenants on a dedicated realm need a per-realm routing step at login.
- **Negative:** Authorisation (RBAC + ABAC) stays in SupportX's own policy layer, not in Keycloak.

## Notes

Accepted at bootstrap (architecture.md §19 listed it as *Proposed*). Owner set by D-007 until a tech lead is appointed.

## Revised 2026-10-22 (D-010)

Tenancy in Keycloak changes from one realm per tenant to **one shared realm using Keycloak
Organizations** for tenants by default. A **dedicated realm** is created only for tenants that need
custom SSO configuration that cannot live in the shared realm. On-prem (single tenant) uses one
realm. Reason: realm-per-tenant does not scale to large SaaS tenant counts. The BFF that holds
tokens lives in `backend/app/modules/identity_access/bff` (D-009).
