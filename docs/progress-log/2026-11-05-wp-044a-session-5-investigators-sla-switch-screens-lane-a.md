### 2026-11-05 — WP-044a session 5: investigators, the full-SLA switch, the console screens (lane A)

**Scope:** REQ-PRB-010..014 and -028/029 in the console, D-140 Q3, ADR-040. PR #211.

**Built**
- ADR-040 investigators.
  - A follower row with reason `investigator` and access: view and notes through the existing
    shared scope.
  - Tasks and own worklogs through the parts service's `_work_access`.
  - Never fields, status, assignment or links.
  - `PUT` and `DELETE /problems/{id}/investigators/{user_id}`, audited.
- D-140 Q3: `sla_settings.full_sla`. Registered target-dates-only types (problems) count only
  resolution targets until it is on, and response targets are refused on save (`full_sla_off`).
- The catalogue gets `problem_types` and `root_causes`. WorkItemOut gets `status_before_pause`.
- Lane B's review:
  - 0077's downgrade folds back only the exact upgrade shape (scope and condition), and refuses
    otherwise;
  - investigators touch only their own worklogs.
- Lane C's request: 0076 and 0089 widen and narrow code checks from their live definitions.
- The merge of main (#200) put 0076 after 0074.
- Console:
  - `/problems`, `/problems/new` (prefill, from many, similar, the default template) and
    `/problems/:id` (status bar shared with incidents through an action override, guided steps,
    caused incidents, investigators, copy);
  - "Create problem" on incidents;
  - labels in en/ar/ur.
- e2e `problems.spec.ts`: from an incident with similar problems and a live owner, the guided
  analysis, and Arabic with axe.

**Checks:**
- ruff, mypy (997 files), import-linter;
- backend unit tests (1493);
- DB tests for problems, parts, the grants migration and SLA (all pass);
- tsc, eslint, prettier, labels (65), console (516 + the new 3), portal (31);
- OpenAPI diff against main: no breaks;
- stack smoke dispatched on b2420bbf.

**Reviews:**
- #214 stage engine: re-reviewed, approved.
- #213: approved.
- ADR-041 / 0090 tables: reviewed.
- Lane B told about 17 unlabelled audit actions (#218 fixes them).
