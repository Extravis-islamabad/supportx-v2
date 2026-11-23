### 2026-11-11 — Workflow step forms, lane C (QA F-05 follow-up)

Branch feat/workflow-node-forms. The coordinator asked that every workflow step type have a form, so admins never type JSON (rule d), before WP-058b S3 resumes. The JSON editor stays only as the "Advanced" view.

**Done**

- **Approval:**
  - the record's roles by name, groups and named people;
  - how they decide (any one, every approver, majority).
  - The palette's `NodeTypeOut` gains `roles`, the record type's approval roles. It is additive, and the OpenAPI diff is clean.
- **Field update:** rows of a settable field and its value, using the conditions editor's `ValueInput`.
- **Webhook:**
  - address, request type, record fields sent and the step's own headers;
  - the number variable that keeps the response status.
- **Set variable:** a declared variable, then a fixed value of its kind or a field of the record.
- **Split:** two to ten named branches.
- **Join:** all, first, or a number of branches.
- **Sub-flow:** another workflow of the type, by name.
- **Function:** its name, inputs from the record's fields, outputs into variables, and a time limit.
- **Retries:** "Try again if it fails" (count and seconds) on every command step that has a form here.
- **Variables tab:** in the designer, with name and kind and the server's name rule checked as you type. Variables are saved and undone with the steps.

**Checks**

- `tests/test_*.py`: 493 passed, 11 skipped.
- `test_workflow_designer_api.py`: 3 passed.
- events-check, `make generated`, the OpenAPI diff and `make frontend-lint`: clean.
- Vitest: the 9 new form tests, `@supportx/flow` 15, and the designer suites one at a time (the parallel run timed out under load 31).

**Follow-up**

- When #402 lands (note and tasks forms, step names), merge main here; NodeForms.tsx and nodes.ts both add entries.
- Note and set status still have no retries field.
