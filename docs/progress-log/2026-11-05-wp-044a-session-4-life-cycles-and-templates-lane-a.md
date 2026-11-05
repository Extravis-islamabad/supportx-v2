### 2026-11-05 — WP-044a session 4: named life cycles and the major problem template (lane A)

**Scope:** REQ-PRB-017 AC1 and REQ-PRB-025 AC1, plus D-140 recorded. PR #211 (draft).

**Built:**
- A type may seed more than one transition set: `WorkItemType.other_lifecycles`.
  `work_item_transitions.lifecycle` is now part of the key, and existing rows are "standard".
- A template chooses a set (`work_item_templates.lifecycle`, checked against the type's sets).
  A record keeps the one it was created with (`work_items.lifecycle`).
- Every move of a record runs its own set: action states, targets, assignment moves,
  fulfilment, transition settings.
- The problems' "guided_analysis" set (Appendix A):
  - investigate, analyse, confirm_root_cause, await_fix, resolve (with the resolution rules),
    start_review, close;
  - nothing closes before the review;
  - the cause can be rejected and the fix can fail, both back to the why-analysis.
- New tenants get the major problem template on that set.
- The catalogue lists every set's transitions. Records, templates and transitions carry
  `lifecycle`.
- Labels in en/ar/ur for the steps, the actions, the two templates and the sets.
- D-140 records Haider's Q1-Q8 answers, and PROGRESS maps each one to a session.

**Checks:**
- ruff, mypy (971 files), import-linter;
- backend unit tests (1478);
- DB tests for problems, incident settings, migrations, incidents, service requests, automation,
  custom fields and portal (135 + 34, all pass);
- tsc, eslint, prettier, labels (65), console (500), portal (28).

**Also (cross-lane):**
- I reviewed ADR-041 and the 0090 tables and asked for changes; lane C took them.
- I reviewed the #214 stage engine and asked for changes: closure, automation and
  required-field checks, the disabled-path 500, entry order ties, and (later) the rail after
  going back and guard reasons on offers.
- I approved lane C's #213 composer change.
