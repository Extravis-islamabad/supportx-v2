### 2026-11-12 — Workflow step forms follow-up, lane C (#406 reviews)

Branch feat/workflow-forms-followup. These are the non-blocking points from lane A's review of #406.

**Done**

- **Approval step roles:** named with the admin's own labels from `GET /api/v1/<type>/settings/roles` (changes, releases; new hook `useRoleDefs`). Without the settings permission, they fall back to the role's code label.
- **Role and group selects:** capped so the approval never names more than 50 approvers in all.
- **Change approval help line:** says a change's requester and owner never decide on it, even when named.
- **Retries:** "Try again if it fails" on the set status and note steps, so every command step with a form has it.

**Checks**

- The designer Vitest files one at a time: node forms 9, more forms 12, workflows 6, versions 1, test panel 3, runs 3.
- The labels package (65 tests), tsc and ESLint.
