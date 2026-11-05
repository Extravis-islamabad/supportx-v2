# 2026-11-05: WP-044b session 1, problem analysis, evidence and impact (lane A)

**Scope:** D8 of ~/Desktop/wp-044-plan.md (REQ-PRB-030, -032, -033; D-140 Q7). Draft #222,
branched from #211's head; main is merged in once #211 lands.

**Built:**
- Migration 0078: `root_cause` and `symptoms` on work_items. Reversible: the columns are only on
  problems, and the downgrade drops them.
- Permissions:
  - `problems.edit_analysis` to change the root cause or symptoms (on create too);
  - `problems.view_root_cause` to read the root cause. Without it the record returns null with
    `root_cause_hidden`, and the history drops those changes.
- `confirm_root_cause` refuses with 422 `required_to_confirm_cause` until a root cause is
  written. The action state lists it as missing.
- The record lists `analysis_changes`: who last changed each readable field, and when.
- `GET /problems/{id}/impact` and `/evidence`: counted only over the visible caused incidents,
  with `partial` / `left_out` set when some are left out. The evidence panel names its pending
  sources.
- Console: overview, analysis and evidence tabs on the problem page:
  - the fields are edited in place with If-Match and the conflict dialog;
  - the impact figures come with a weekly bar chart;
  - the evidence is a timeline;
  - all of it is live through the record channel.
- Labels (en, ar, ur): the permissions, fields, operation, error code, evidence sources and tab
  texts.

**Tests:**
- DB tests:
  - test_problem_analysis_api: hidden and widened root cause, edit refused, history, the right
    needed on create, last changed, impact and evidence partial, RLS;
  - test_problems_api: the cause can't be confirmed without a root cause.
- Vitest: the analysis and evidence tabs.
- An e2e spec (problems.spec.ts, the analysis test). It runs in the stack smoke, not locally:
  QA only on the shared stack.
- Green locally:
  - ruff, mypy, import-linter;
  - the non-DB backend tests (486);
  - the problem DB tests (19);
  - eslint, prettier, tsc;
  - console (518) and labels (65).

**Not yet:** see PROGRESS (impact by service and CI, the change and release evidence, cost,
copying the analysis).
