# ADR-022: Authorization policy layer: SupportX-owned roles, scoped grants, one policy service

- **Status:** Accepted
- **Date:** 2026-10-23
- **Source:** architecture.md §11.2; D-029; WP-016
- **Owner:** Haider (Product Owner)

## Context

Until WP-016 access checks were interim (`user_type == technician`, the `tenant_admin` realm
role). §11.2 requires role- and attribute-based rules (module/action, scope, attribute, field,
segregation of duties) evaluated in one layer used by the API, search, realtime and AI agents,
cached and invalidated by events.

## Decision

1. **SupportX is the source of truth for authorization** (D-029). Keycloak authenticates; realm
   roles are mapped once to SupportX roles at a user's first login, tracked by
   `users.roles_mapped_at`.
2. **Permissions are `module.action`, declared by modules** in their ModuleSpec; the ITSM ones are
   reserved in identity_access until their modules exist. Each names a licence feature; the
   catalogue is validated at startup.
3. **Roles hold grants (permission, scope, optional filter-DSL condition).** System roles are
   code-defined (tenant admin = whole catalogue), immutable and stored only for assignment; custom
   roles live in `role_permissions`. Scopes: all, site, group, own; only `all` covers the others.
4. **One policy service** (`identity_access/service/policy.py`): `authorize`, `scope_filter`
   (SQL predicate built from grants, conditions compiled by the WP-008 filter compiler),
   `authorize_stored`, `visible` (field rules), SoD rules per resource type.
5. **Every route declares access** (`require_permission`, `require_signed_in` or `@public_route`);
   a guard test enforces it. Core defines the seam; identity_access implements it.
6. **Compiled subjects are cached in Valkey per tenant generation.** The generation is bumped after
   commit in the changing process (`access_changed`) and by an event consumer for all others.
7. **Admin protections in the service layer:** no privilege escalation (grants ⊆ caller's grants
   unless tenant admin), immutable system roles, last-admin protection under an advisory lock,
   reassignment required to delete a role in use. Same-tenant composite foreign keys on all link
   tables.

## Consequences

- **Positive:** one rule written once applies to lists, records, search, realtime and agents;
  roles are designed in the product per tenant; licence and permission checks compose; changes
  take effect on the next request.
- **Negative:** each request reads the compiled subject from Valkey (~0.3 ms); a cache entry
  compiled concurrently with a change can survive until the consumer's bump (sub-second).
  Attribute conditions are available only for resources that registered a resource type.
- **Follow-ups:** SSO group → role mapping; design-time SoD conflict warnings in the role editor;
  condition editing in the UI; search/realtime/agent call sites as those features land (WP-011+).
