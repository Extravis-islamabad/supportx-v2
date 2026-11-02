### 2026-10-23 — WP-016 authorization policy layer
- Decisions: D-028 (`@ant-design/icons`, `@hookform/resolvers` approved), D-029 (SupportX DB is the
  source of truth for authorization; Keycloak roles mapped once at first login). ADR-022.
- Backend: permission catalogue as code (30 permissions: users, roles, profile, sites, groups,
  settings, licence + reserved requests/problems/changes/releases/assets/cmdb/knowledge/reports),
  each tied to a licence feature; `ModuleSpec.permissions`. Migration 0006: roles,
  role_permissions (scope + filter-DSL condition), user_roles, sites, support_groups, members
  (RLS, same-tenant composite FKs, guard passes), users.roles_mapped_at.
- Policy service: compiled subjects (grants, memberships, entitlements) cached in Valkey per
  tenant generation; `authorize`, `authorize_stored`, `scope_filter` (SQL, OR over grants, DSL
  conditions via the WP-008 compiler), `visible` (hide/mask), SoD rules (`own_request_approval`).
  Invalidation after commit (`access_changed`) + consumer `identity_access__invalidate_authz`.
- Enforcement: `require_permission` / `require_signed_in` / `@public_route` on every route, guard
  test proven against a planted route; interim checks (technicians_only, tenant_admin role,
  admin-only Users page) replaced; `/auth/me` returns SupportX roles + effective permissions;
  licensing's admin notices use `licence.manage`.
- Admin API: permissions, roles CRUD (ETag/If-Match, Idempotency-Key), user access, role
  assignment, sites/groups with members. Protections: system roles immutable, no escalation, last
  tenant admin (advisory lock), role-in-use reassignment.
- Console: Admin (tabs Users / Roles), role editor with permission matrix (scope per permission,
  locked when outside the plan, read-only system roles), user access drawer (roles, sites,
  groups), menus and pages driven by permissions. en + ar labels for every permission, scope,
  role, reason and screen.
- Found by tests: `site`/`group` were wrongly treated as covering `own` (lost own rows) → only
  `all` covers; membership changes only reached the cache via the consumer → after-commit hook.
- Found by CI: on a cache miss the subject and the entitlement were read on a second connection
  while the request held one, so 5 concurrent requests deadlocked CI's 5-connection PgBouncer
  pool → both read through the request's connection (`REQUEST_SESSION_STATE`), test asserts one
  connection per request. Dark mode's selected menu/tab text was ~1.6:1 (Ant Design's dark
  primary) → light brand tint, contrast test for several brand colours. axe scans only the open
  modal (the page behind its mask is inert).
- Tests: backend 686+ (matrix, scopes on 100k rows ~1 ms/page, rules SQL ≡ memory, masking, SoD,
  escalation/system role/last admin/cross-tenant/stale cache attacks, guard, mapping once);
  frontend 110 Vitest; Playwright 10 journeys incl. custom role → menus and axe (roles list,
  editor, drawer; Arabic + dark).
- Follow-ups: SSO group → role mapping; condition editing in the UI; design-time SoD warnings;
  user_type (seat counting) still follows Keycloak; search/realtime/agent call sites (WP-011+).
