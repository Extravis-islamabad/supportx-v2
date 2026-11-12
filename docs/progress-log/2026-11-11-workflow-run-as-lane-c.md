### 2026-11-11 — A workflow's run-as identity gets roles, lane C

Branch feat/workflow-run-as. The coordinator approved the plan on 2026-11-11, and lane B gives the blocking review. It was found from the workflows e2e, which had been red on main since WP-048b S5.

**Found**

- Publishing made the run-as identity "Workflow: <name>" with no role. Nothing routed to identity_access's guarded `assign_service_identity_role`.
- So every step that changes the record (set status, field update, note) failed on every record, shown as "Work Item Not Found". The DB tests never noticed, because their helper runs workflows as the admin.
- The general `PUT /users/{id}/roles` could reach a service identity. Lane B closed that in #413, and this PR doesn't touch it.

**Done**

- **API:**
  - `GET /automation/workflows/{id}/run-as` returns the identity, its roles, and the roles it may be given (the server's own rule, `roles_for_service`).
  - `PUT` and `DELETE …/run-as/roles/{role_id}` go only through `assign/remove_service_identity_role`. They need workflows.manage, the admin's no-escalation check applies, and both are audited (access category).
  - A role change writes `automation.workflow.run_as_changed` (IDs and codes only) to the workflows channel, so open designers refresh.
- **identity_access read helpers:** `roles_for_service`, `roles_held`, `service_identity`.
- **Runtime:** a refused step on a record that exists fails with `workflow_identity_not_permitted`, worded on the Runs tab and the record panel. It names nothing about the record.
- **Designer:**
  - a "Runs as" tab shows the identity, its roles and a picker from the server's list;
  - a warning on the canvas appears while steps that change the record exist and no role is held, and publishing asks first (it never blocks);
  - help text says the role must reach every record of the type, because a group-limited role reaches none for an identity in no group.
- **e2e (`workflows.spec`):**
  - the keyboard journey sees the warning in en and ar, publishes through the confirm, gives the identity an "E2E" role, and the warning goes;
  - the skip journey fails on the identity's missing right instead of an invalid impact, which validation now refuses at publish.

**Checks**

- New DB tests (4): no role, a role given and taken, tenant admin refused and never offered, technicians and other tenants refused.
- The related workflow suites; `tests/test_*.py`.
- events-check, `make generated`, the OpenAPI diff, mypy and frontend-lint.
- Vitest: 3 new tests.

**Follow-up**

- Connector service identities (integrations) have the same missing roles path; tell the coordinator.
