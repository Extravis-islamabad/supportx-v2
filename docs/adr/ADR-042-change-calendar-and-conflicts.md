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
- The override **names the blocking freezes it passes** (`window_ids`, as the 409 lists them),
  and they are stored with the change. Only those are passed: a different freeze, or one added
  later, still refuses the save until someone allowed passes it too (lane B's review of #376).
  A maintenance window that blocks is never passed by a freeze override.
- It is audited (`change.freeze_override`, with the windows; refused attempts too) and kept in
  the record's history.
- Editing a passed freeze's dates later widens what the override covers for that change. This
  is deliberate: the window is the same decision, and the edit is itself audited
  (`change.window_changed`) by someone holding `changes.manage_windows` (lane B's review).
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

## Addendum A (WP-058b S2): releases, by planned stage

*Proposed by lane C; agreed in principle by lane A on 2026-11-11, before the code. Lane A gives
the blocking review of this text in the S2 PR. The coordinator's answers (a)-(c) of 2026-11-11.*

1. **Planned stage per type.** `domain/change_windows.PLANNED_STAGE`: a change plans its
   implementation, a release its deployment. A record's planned time is that stage's window and
   its planned downtimes. The calendar (WP-058b S1) and the guard read the same map.
2. **The same pure check.** A release is in a window's scope by the same rule as a change. Monthly
   windows use the tenant's zone through `window_of(row, zone)`, so a release's freeze check uses
   the tenant's local days too. Every deployment is guarded; per-environment guarding waits for
   WP-053 (coordinator (b)).
3. **Outside maintenance.** D-156's `outside_maintenance_blocks` is the change type's setting
   only. A release always warns outside maintenance, unless a new decision gives releases their own
   setting (and column).
4. **Overlap across types** (coordinator (a)). Open changes and releases planned at an overlapping
   time meet on the same group or site, or when their planned downtimes name the same service or
   CI (stored IDs only). An overlap only warns, and names the other record by ID and type, never
   its subject. `_others` is one query per type, under the tenant's RLS.
5. **Booked twice** (`role_booked`, REQ-REL-041). A release manager or engineer (the release's
   details or its role holders) on two releases whose deployments overlap. Releases only, warn
   only.
6. **Guard.** It runs for both types on every path that moves the planned time. The 409 stays
   `change_window_blocked` with the same params (kind, window_id, window_ids, count); its text
   no longer says "change".
   - **Changes, unchanged:** what passes is the override's freezes (and, for the move into
     implementation, the emergency CAB's); an emergency change's window is marked, not refused.
   - **Releases:** only the release's own override (`releases.override_freeze`, 0139: the
     release manager and administrators, a reason, SECURITY audit, history, refused on a closed
     release). There is no CAB path, and a release on its emergency path is refused like any
     other; a release emergency route would be a new decision.
   - Both are bound to window IDs; a blanket pass never exists.
7. **Acknowledging a warning** (releases only, REQ-REL-041 AC3). A conflict's key is its kind,
   what it is with (a window, a record, or the maintenance windows in force) and both sides'
   versions of their planned times. An ack (who, when, why) holds for its key: it lapses when
   either side moves, and a new conflict never inherits it. A block is never acknowledged; it goes
   through the override. Changes have no acknowledge step (lane A).
8. **Live.** Conflicts refetch on both types' list channels and on the windows broadcast.
