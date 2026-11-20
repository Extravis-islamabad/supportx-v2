# ADR-053: Fine-grained access to assets and configuration items, narrow-only

- **Status:** Proposed (WP-053 S3a, migration 0183; semantics set by D-172, Haider through the coordinator, 2026-11-16)
- **Deciders:** Haider (Product Owner), through the coordinator; lane C reviews (blocking, D-175)
- **Related:** REQ-CMDB-029, REQ-CMDB-030, WP-053 S3; ADR-047 (field access per role, the same compile pattern); ADR-022 (one policy layer); D-172

## Context

Assets and configuration items (CIs) are seen today through role scope only: `assets.view` / `cmdb.view` with `all`, `site`, `group` or `own`. REQ-CMDB-029 asks that some people see only some of them, for example a printer technician who sees printers only, or a site team that sees one building's servers. REQ-CMDB-030 asks that impact analysis and maps show records a person may not see as "restricted" placeholders, never as a name, type or attribute.

D-172 sets the semantics: rules **only reduce** what a role already shows, they **combine as a union**, and they **never grant**.

## Decision

### 1. Rules

- A rule is **(role, resource, criteria)**.
  - The resource is `asset` or `ci`.
  - The criteria are a small fixed set of fields per resource, each a list of values: type (with its subtree), site, owner group, managed-by group, and a criticality ceiling.
  - Modules register their criteria fields through a port, `register_access_criteria(resource, fields)`, so identity_access never knows asset or CMDB columns. This is the ADR-047 field-catalogue pattern.
- **Table:** `role_resource_access` in identity_access, tenant first, RLS forced, with an RLS test.
  - It carries a `version` (If-Match).
  - Every change is audited with before and after.
  - At most 500 rules per tenant; more answers 422 `limit_reached`.
- **Changes** need `roles.manage` and RecentAuth. Each change emits `identity_access.resource_access.changed`, and that event is added to the authz consumer's `TRIGGERS`. The person's **next request** sees the change, with no sign-out needed, the same as role and field-access changes.

### 2. Semantics (D-172)

- A rule never widens a role's scope. What a person may see is **role scope ∩ (union of their rules for that resource)**, worked out as follows:
  - **No rule:** if none of the person's roles has a rule for the resource, role scope applies unchanged.
  - **Some roles have rules:** take each role's allowed set, which is its own scope narrowed by its own rules, then the union across the person's roles. So a person with two roles, one narrowed and one not, sees everything the un-narrowed role sees: the clearest wins, as in ADR-047 §2. The admin guide says so plainly.
  - **Tenant admins** are never narrowed (break-glass and setup).
- The **effective-access view** (`GET /people/{id}/access-rules`) is computed from the same compile as the Subject, not a second implementation. A test checks that the two agree.

### 3. One compile, everywhere

- `FieldAccess`-style compile into `Subject.extra["resource_access"] = {resource: [predicate, …] | None}`. None means not narrowed. Every subject kind gets it: browser sessions, mobile sessions, API keys, and integration Runs-as identities.
- **Applied in one choke point per module.** Each of these takes the subject's predicate:
  - `assets.scope_filter(subject)` and `cmdb.scope_filter(subject)`;
  - every list, search, picker and lookup;
  - realtime fan-out (`ChannelAccess`: no event about a record the person may not see);
  - reports and exports (the reporting source filters rows);
  - AI sources;
  - mention passages.
- **A record outside the person's set answers 404**, never 403, so nothing reveals that it exists.
- **Impact and the map** (REQ-CMDB-030) walk the tenant's whole graph, so paths stay correct, then redact every node outside the set to `{restricted: true}`, with no name, type or attribute. A test proves that no placeholder carries any field.

### 4. Performance

Predicates turn into SQL on indexed columns (tenant first, the type subtree through a type-path column). There's a 10k-asset, 100k-CI timing check on lists, pickers and impact at depth 5, which must stay under 2 s with redaction.

### 5. Licensing (D-172, Haider 2026-11-16)

- **Professional** (no extra feature): the plain role scopes `all`, `site` (own sites), `group` (own groups) and `own` for both **CMDB and assets**, so a multi-site Professional tenant never has to show every CI or asset to everyone.
  - CMDB `group` means the CI's owner group or managed-by group is one of the person's groups.
  - Assets `group` needs a managing group on assets, which isn't there yet: it falls back to the member's sites today. It's added with S3.
- **Enterprise:** only the custom rule builder in this ADR, the `fine_grained_access` feature (rules on type, criticality and so on).
- **Existing rules always apply**: a lapse never exposes data. With the feature lapsed, an admin can still view and remove rules, audited; adding or changing one needs the feature.

### 6. Erasure and audit

Rules reference roles only, never people, so no erasure port is needed (ERASURE_EXEMPT: "roles only"). Every rule change goes to the audit chain.

## Consequences

- One mechanism narrows both assets and CIs, and every read path uses it. A path that forgets it is caught by an import-linter contract (no module queries CMDB or asset tables directly) plus a guard test listing the choke points.
- Narrow-only means a misconfigured rule can only hide things, never expose them. The worst case is "can't see enough", which the effective-access view explains.
- Rules apply to people and integration identities alike, so a connector's reach can be narrowed too.

## As built (S3a)

- **Compile per role.** Each role's allowed set is that role's scope narrowed by that role's own rules; the sets are joined with OR across roles. A role with no rule for the resource contributes its plain scope, so it is never narrowed by another role's rules. The shortcut that skips filtering for an `all`-scope reader is off whenever any of the reader's roles has a rule.
- **Writes.** Creating or moving a record so that it would fall outside the writer's set answers 403 with the reason `out_of_scope` (the writer already saw the record or is choosing its values, so a 404 would reveal nothing new and only confuse). Reads outside the set stay 404.
- **Guard.** A test walks every API route of `assets` and `cmdb` and fails on any route that reads or writes their records without the scope filter, unless it is listed with a reason.
- **Erasure holdings** (ADR-052) report true totals, plus a count of what lies outside the reader's view (`assets_held_outside_view`, `cmdb_cis_owned_outside_view`), never the records themselves.
- **Assets `group` scope** now uses `assets.managed_by_group_id` (same-tenant FK to groups) in every edition, replacing the site fallback.
- **Not narrowed by design:** `GET /assets/availability` is a shared loan pool that names no asset or person (D-179).
