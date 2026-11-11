# ADR-042: The change calendar and its conflict model: windows as data, one pure check, a guard on every save

- **Status:** Proposed (WP-045c; number reserved 2026-11-04, plan approved by the coordinator 2026-11-11)
- **Date:** 2026-11-11
- **Source:** WP-045c; parity file 05 §9-§11 (REQ-CHG-062..077); architecture.md §6.2, §6.5, §8;
  ADR-041 (the stage engine); D-144 (the emergency override's pattern); D-156 (defaults, held)
- **Owner:** Haider (Product Owner)

## Context

Changes are planned in time: an implementation window, planned downtimes and, later, CIs and
services that are down. Tenants say when changes must not happen (freezes) and when they should
(maintenance windows), for everyone or for some sites, groups, services or CIs. A change planned
against these must be told why, at once, on every save, and a freeze must be able to stop it.
Lane C's releases (WP-058b) plan the same way and should not build a second model. The CMDB
(lane B, WP-049/050) is not on main yet.

## Decision

### 1. Windows are data

- `change_windows` (migration 0132; RLS) holds a window's kind (`freeze` or `maintenance`), its
  mode (`block` or `warn`), its times, an optional **weekly** repeat until a date, and its
  scope: sites, groups, services and CIs. All empty means the whole tenant.
- Services and CIs are IDs until the CMDB serves them. A window named only for them reaches no
  change; it is never silently tenant-wide.
- Defaults (D-156, held for Haider): a new freeze **blocks**, a maintenance window **warns**,
  and only weekly repeats exist in v1. A change of any of these is a default value, never a
  redesign.

### 2. One pure check

`domain/change_windows.py` decides, without I/O, the conflicts of a change's planned times
(its implementation window and its planned downtimes):

- **freeze:** an occurrence of a freeze in scope overlaps; the freeze's mode decides whether it
  blocks;
- **outside_maintenance:** maintenance windows are in scope and none holds the whole time. It
  warns unless one of them blocks. A one-off maintenance window counts within a week of the
  change, and a weekly one for as long as it repeats, so a tenant's old windows never warn for
  ever;
- **overlap:** another open change in the same group or at the same site is planned at the same
  time. This only warns.

Intervals are half-open, so a change may start the moment a freeze ends.

### 3. A guard on every save, and a conflicts view

- The work item service calls `service/change_conflicts.guard` whenever a change's
  implementation window or a planned downtime is saved. A blocking conflict refuses the save
  with 409 `change_window_blocked`, naming the first window, and the rest are shown.
- `GET /changes/{id}/conflicts` lists every conflict with why. `change_conflicts` never imports
  the work item service, so the dependency runs one way.

### 4. The freeze override, as D-144's

- `POST /changes/{id}/freeze-override` needs `changes.override_freeze`, decided on that change at
  the scope it was granted (all, its site or its group), a reason and If-Match.
- It is audited (`change.freeze_override`, refused attempts too) and kept in the record's
  history. From then on the change's blocking freezes are shown, not enforced.
- The change manager holds it. Tenant administrators hold every permission, so they may override
  too, as with D-144. Team leads and technicians never do.

### 5. Live, and reused

- Window changes go through the outbox (`work_items.change_window.changed`) to a broadcast
  (`work_items.change_windows_changed`), so calendars and settings refetch (rule 5c).
- The calendar (S3) reads windows by range (`GET /change-windows?start=&end=`) and changes by
  their schedule.
- Releases reuse the check and the guard when lane C plans them with windows. The model has no
  type of its own beyond the scope rule.

## Consequences

- One place decides conflicts; the screens only show what it says, and the server enforces
  blocks.
- No recurrence rules beyond weekly in v1 (D-156 (c)). Full rules are a later, additive change to
  `Window.occurrences`.
- CI- and service-scoped windows wait for the CMDB. Their IDs are already stored, so no
  migration is needed then.
- The maintenance reach (a week) is a v1 rule of thumb. It is one constant, `MAINTENANCE_REACH`.
