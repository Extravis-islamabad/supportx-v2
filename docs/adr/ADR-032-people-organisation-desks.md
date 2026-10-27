# ADR-032: People and organisation structure — SupportX owns the person record, desks from the start, usage-checked removal

- **Status:** Accepted
- **Date:** 2026-10-27
- **Source:** WP-021; architecture.md §6.1, §7.1, §7.2, §11.1, §13; docs/specs/parity/11-admin-users-security-audit.md REQ-ADM-001..005, REQ-ADM-031, REQ-ADM-035, REQ-ADM-037, REQ-ADM-039; REQ-ESM-002; D-061, D-062, D-073, D-092
- **Owner:** Haider (Product Owner)

## Context

Until WP-021 a user row was a copy of the Keycloak profile, refreshed at every sign-in, and a
person could exist only after signing in once. ServiceDesk Plus parity needs people that admins
add and edit, contacts who never sign in, imports, departments, richer sites and groups, and
(for enterprise service management) desks that every record belongs to. Lane B's WP-039 maps
directory (SSO) attributes onto departments and sites, so both need stable lookup keys.

## Decision

1. **SupportX owns the person record once it exists (D-092).** The first sign-in creates the
   person from the ID token, or links a person added by an admin or an import by email (any
   case); after that a sign-in records only `last_login_at`. Name, email, type and language are
   edited in SupportX and never overwritten by Keycloak. Keycloak's realm roles are still
   mapped once (D-029) for people created by sign-in; people added in SupportX get their roles
   in SupportX (`roles_mapped_at` set at creation).
2. **Email is optional; `can_sign_in` separates people from contacts.** Signing in needs an
   email address. A refused sign-in (deactivated, sign-in off) rolls back, linking nothing.
   Stopping sign-in or deactivating ends the person's sessions after commit (Valkey end mark
   per tenant and person; sessions created before it are refused).
3. **Technicians are licence seats.** Becoming a technician (added, imported, promoted,
   reactivated) reserves a seat through the entitlement interface; deactivation frees it.
4. **Nothing about a person is deleted.** Deactivation keeps records, roles and groups;
   reactivation lists what the person still holds and keeps only what the admin confirms.
5. **Desks from day one (D-061, D-062).** Every tenant has an IT desk (`is_default`), created
   by the migration for existing tenants and on first need for new ones; every record, template
   and support group belongs to a desk. More desks need the ESM feature and count against the
   licence limit `desks` (renamed from `departments`, D-092).
6. **Departments** have a name, a code unique per tenant (directory sync matches by code, then
   by English name: `find_department`, `find_site`), a site, a head and a parent; loops are
   refused. People have a site, a department and a manager (loops refused).
7. **Removal is checked by usage, across modules.** organization owns sites, groups and
   departments but cannot read other modules' tables, so modules register usage checks
   (`register_usage`): identity_access counts people, work_items counts records. A unit in use
   answers 409 with the counts; the admin makes it inactive instead. The default site cannot go.
8. **Technician visibility is a tenant setting (D-052, D-073).** `access_settings` holds the
   first-run answer, "group" until answered. "all" widens the technician defaults that modules
   declare at `group` scope when permissions are compiled; a change refreshes compiled
   permissions and every technician's realtime access.
9. **Imports run in the background.** The API stores the file on a queued `people_imports` row;
   a schedule in the consumers worker reads it (CSV UTF-8 or .xlsx through openpyxl read-only,
   values only; size, row, column and cell limits; the zip is checked for "bomb" ratios before
   opening), applies rows in batches with a savepoint per row, commits progress with an event
   per batch (live screen), clears the file when done and keeps per-row problems as codes.

## Consequences

- Keycloak profile changes (name, email) no longer reach SupportX by themselves; directory
  sync (WP-039) must write through the people service.
- Raw SQL inserts of users, records, templates or groups must set `first_name` and `desk_id`
  (test fixtures and dev seeds were updated).
- New tables (desks, departments, group_sites, access_settings, people_imports) follow RLS and
  have isolation tests; migration 0023 is reversible (people without a subject get a local one).
