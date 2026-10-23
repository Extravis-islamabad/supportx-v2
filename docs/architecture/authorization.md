# Authorization: roles, permissions and scopes

Who may do what in SupportX (architecture.md §11.2; WP-016; D-029; ADR-022). One policy layer
decides for the API today and, with the same functions, for search, the realtime fan-out and AI
agents later. PostgreSQL row-level security stays underneath as the final tenant boundary.

## The short version

- A **permission** is `module.action`: `users.view`, `requests.assign`, `changes.approve`.
- A **role** is a set of permissions, each with a **scope**: which records it reaches.
- Users get **roles**; their effective permissions are the union of their roles' grants.
- A permission whose **licence feature** the tenant lacks is never held, whatever the roles say.
- **SupportX decides, not Keycloak.** Keycloak signs people in. On a user's first login in a
  tenant their Keycloak realm roles are mapped once (tenant_admin → Tenant administrator,
  technician → Technician, otherwise Requester); after that only SupportX changes them.

## Scopes

| Scope | Reaches |
|---|---|
| `all` | every record of the kind |
| `site` | records of the sites the user belongs to |
| `group` | records of the support groups the user belongs to |
| `own` | records the user owns: they requested it, it is assigned to them, or it is them |

Only `all` includes the others. `site`, `group` and `own` reach different, overlapping sets: a
user's own request can belong to a site they are not a member of. A role can grant one permission
at several scopes; the user sees the union.

Sites and support groups (with their members) live in the organization module:
`/api/v1/organization/sites`, `/api/v1/organization/groups`.

## How a permission check works

1. The route declares what it needs: `Depends(require_permission("users.view"))`. Every route
   must declare a permission, `require_signed_in()` (own data), or `@public_route` (health, login);
   a guard test fails for any route that declares nothing.
2. The caller's **subject** is loaded: their compiled permissions, scopes, memberships and the
   licence features. It is compiled once and cached in Valkey (`<prefix>authz:<tenant>:<user>`).
3. If the permission is not held at any scope: 403 `permission_denied` with a reason
   (`no_permission`, `not_entitled`).
4. Lists add `scope_filter(subject, permission, resource_type)` to their query: an SQL predicate
   (OR over the user's grants) so a list only ever returns rows the user may see. No grant means
   an empty list, never an unfiltered one. It combines with the request's own filter DSL.
5. Single records are checked with `authorize(...)` (in memory) or `authorize_stored(...)` (the
   same scope filter in SQL), plus segregation-of-duties rules; responses pass through
   `visible(...)` for field-level hiding or masking.

Cached checks cost about 0.3 ms (Valkey) per request; the decision itself is microseconds. A
scoped page over 100,000 rows takes about 1 ms with the indexes in place.

### When changes take effect

Every role, assignment or membership change, and every plan change, makes the tenant's cached
subjects stale: immediately after the change commits in the API process that made it, and in
every other process when the change's event reaches the `identity_access__invalidate_authz`
consumer (normally well under a second). The user's **next request** uses the new permissions.
The browser refreshes `/auth/me` on focus and after admin changes; menus follow.

## Attribute rules

A grant can carry a condition in the shared filter DSL (the same JSON as list filters), e.g.
"HR cases only":

```json
{ "permission": "requests.view", "scope": "all", "condition": { "field": "category", "op": "eq", "value": "hr" } }
```

The condition is compiled by the filter DSL compiler (WP-008) against the resource's allowlisted
fields, so lists filter in SQL. Single records can be checked in memory with the same semantics
(`contains`/`starts_with` case-insensitive, `ne`/`not_in` include empty values); relative-date
operators (`today`, `last_n_days` …) need SQL: use `authorize_stored` for those.
Conditions are accepted only for permissions whose module registered a resource type
(today: `users`); others are refused with `condition_not_supported`.

## Field-level visibility

A resource type lists restricted fields: `FieldRule(permission, "hide" | "mask")`. Without the
permission, the field comes back `null` (hide) or `••••` (mask). Example in production: a user's
`last_login_at` is only shown to subjects holding `users.manage`.

## Segregation of duties

A resource type can attach rules to a permission: `SodRule(code, violated)`. The shipped example
(`own_request_approval`): a user cannot approve a record they requested themselves, even with
`changes.approve`. The decision's reason is the rule's code, translated as
`permission_reason.<code>`.

## System roles

| Role | Holds |
|---|---|
| Tenant administrator | every permission in the catalogue, at its broadest scope (new modules included automatically) |
| Technician | requests (all, incl. assign/close), problems view (all) / manage (group), changes view + create, releases/assets/CMDB/knowledge view, assets + knowledge manage (group), reports, users/sites/groups view, own profile |
| Requester | own requests (view, close), create requests, knowledge view, own profile |

System roles cannot be edited or deleted. Their permissions are defined in code
(`identity_access/domain/permissions.py`), so they grow with the catalogue.

## How admins build roles

**Admin › Roles** (needs `roles.view`; editing needs `roles.manage`):

- The matrix lists every permission grouped by module, with its label and description and a
  scope selector (*No access*, then the scopes that permission allows).
- Permissions of features outside the plan are locked (lock icon, upgrade hint).
- Protections enforced by the server: nobody grants a permission or scope they do not hold
  themselves (tenant administrators excepted); editing a role that holds more than you is
  refused; the tenant administrator role can only be given or taken by tenant administrators;
  the last tenant administrator keeps the role; deleting a role that users hold requires a role
  to move them to.

**Admin › Users**: click a user to assign or remove roles (`users.manage`) and sites/groups
(`sites.manage` / `groups.manage`; new sites and groups can be created there too).

The Admin area is visible to anyone holding at least one admin permission (`users.manage`,
`roles.view`, `roles.manage`, `sites.manage`, `groups.manage`, `settings.manage`,
`licence.manage`).

## How a new module declares permissions

1. Add them to the module's `ModuleSpec`:

   ```python
   module = ModuleSpec(
       name="changes",
       feature="change",
       permissions=[
           PermissionSpec("changes.view", "change", ("all", "site", "group", "own")),
           PermissionSpec("changes.approve", "change", ("all", "site", "group")),
       ],
   )
   ```

   (Remove them from `RESERVED_PERMISSIONS` in identity_access: the ITSM ones are reserved there
   until their module exists. Startup fails on duplicates, bad keys, scopes or features.)
2. Add `permission.<key>` and `permission.<key>.description` labels (en + ar; CI checks).
3. Protect routes with `Depends(require_permission("changes.view"))` (CI fails otherwise).
4. Describe the records for scopes and rules once, as a `ResourceType` (owner columns, site and
   group predicates, filterable fields, field rules, SoD rules), and use `scope_filter` in list
   queries and `authorize`/`authorize_stored` for single records.
5. Emit an event for anything that changes access (or call `access_changed(session)`).

## API

| Endpoint | Permission |
|---|---|
| `GET /api/v1/auth/me` → `permissions` (key, broadest scope, scopes, conditional) and `user.roles` | signed in |
| `GET /api/v1/permissions` | `roles.view` |
| `GET/POST /api/v1/roles`, `GET/PATCH/DELETE /api/v1/roles/{id}` (ETag/If-Match, Idempotency-Key) | `roles.view` / `roles.manage` |
| `GET /api/v1/users/{id}/access` | `users.view` |
| `PUT/DELETE /api/v1/users/{id}/roles/{role_id}` | `users.manage` |
| `/api/v1/organization/sites|groups` (+ `/members/{user_id}`) | `sites.*` / `groups.*` |
