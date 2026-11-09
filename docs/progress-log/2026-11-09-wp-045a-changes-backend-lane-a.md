### 2026-11-09 — WP-045a changes on the stage engine, backend (lane A)

PR #299 (feat/wp-045a). Plan: ~/Desktop/wp-045-plan.md, D1 to D7. Spec: file 05, REQ-CHG-002 to -039 (V1).

**Done**

- **D1, the change type:**
  - Appendix A stages, statuses and paths;
  - `changes.*` permissions moved out of identity's reserved list;
  - custom fields (0099);
  - own fields: the change type and the reason for change (0101 table, 0102 lists).
  - The release details code became per-type `DetailsSpec`; lane C agreed and reviewed.
- **D2 and D3, types and templates:**
  - each type is bound to a model, and the type picks the path;
  - standard changes are pre-approved with a history line;
  - a locked plan edit gives a 409 warning, and confirming converts the change to normal through the new `stages.restart()`;
  - five default templates, each binding its type.
- **D4, the guard:** `ChangeGuard`. Stage approvals now open for changes, and implementation needs a matching outcome. The outcomes follow the spec, and 0100 adds `backed_out`.
- **D5, roles:**
  - roles take people or groups;
  - the line manager comes from the requester;
  - segregation of duties (0103), Haider's default: the assigned implementer and the change owner never approve, while members of an implementing group still may. The tenant's strict option, the submit warning and the audit come with WP-045b.
- **D6, creating:** from another record, prefilled and linked as `change_for` (0115); copy, with the parts chosen; retrospective changes.
- **D7, plans:**
  - the backout plan is required before the plan goes for approval;
  - stage rules may name plan sections;
  - schedule rows show `overdue`.

**Tests:** `tests/db/test_changes_api.py` (25) and the change domain tests, plus the release, stage, template and approval DB suites. Labels, OpenAPI and import-linter pass.

**Not yet**

- The built-in change manager role (REQ-CHG-038), after #240.
- CIs, assets and services, with the CMDB.
- WP-045b (CAB, risk) and 045c (calendar, freeze).
- The screens, on UI pass 3's templates (D-147).
