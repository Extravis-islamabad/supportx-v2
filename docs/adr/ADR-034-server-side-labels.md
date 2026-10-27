# ADR-034: Server-side labels — one dictionary, exported from the labels package as JSON

- **Status:** Accepted
- **Date:** 2026-10-27
- **Source:** WP-035 (plan: ~/Desktop/wp-035-plan.md); architecture.md §9.5; CLAUDE.md §5d;
  parity file 09 REQ-RPT-005, REQ-RPT-058, REQ-DSH-045; D-006, D-048, D-100 (D7)
- **Owner:** Haider (Product Owner)

## Context

Labels live in `frontend/packages/labels` (en, ar, ur) and the UI renders every code through
them. Exports (CSV, Excel, PDF), scheduled report emails and notifications are written by the
server, which had no labels. Copying strings into the backend would let the two drift, and
sending codes would break rule d.

## Decision

1. **One dictionary.** `make labels-json` writes `backend/app/shared/labels/resources.json` from
   the TypeScript resources, using Node's built-in type stripping (no new tool). The JSON is
   committed.
2. **Two checks.** A Vitest test in the labels package fails when the JSON differs from the
   resources (keys and values); a backend test fails when the JSON lacks any key of the TypeScript
   files. Changing a label without regenerating the JSON fails CI on both sides.
3. **One function.** `app.shared.labels.label(key, language, **params)`: English fallback for a
   missing translation (as the UI), `{{param}}` interpolation and CLDR plurals (`count=`; Arabic
   zero, one, two, few, many, other) like i18next. A key missing in every language raises
   `MissingLabelError`, so tests catch it rather than a code reaching a reader.
4. **Every server-written text uses it:** report exports and emails (WP-035), notifications
   (WP-023) and mail templates (WP-039). Admin-defined values (categories, custom choices) keep
   their own stored translations.

## Consequences

- **Positive:** the same words in the UI, in files and in emails, in all three languages; Urdu
  and Arabic come for free once the UI has them.
- **Negative:** the JSON (~450 KB) is regenerated after label changes; the checks make forgetting
  it a CI failure, not a silent drift.
