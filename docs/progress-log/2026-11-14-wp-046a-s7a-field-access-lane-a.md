### 2026-11-14 — WP-046a S7 slice a: field access per role (lane A)

- **ADR-047** accepted by the coordinator after lanes B and C reviewed r2; written into
  docs/adr with one correction found while building: `Subject.extra` is not cached, so field
  access is a real `Subject.field_access` field.
- **Migration 0162:** `role_field_access`, custom field `personal_data`/`sensitive`, the
  per-type `custom_text_rebuilding_since` marker; the downgrade refuses while any is in use.
- **identity_access:** domain (`effective`, clearest wins), compile in `PolicyService.compile`
  (roles own, through active groups, or the type's default), service and `/field-access` routes,
  `FieldAccessChanged` event (authz consumer trigger plus a realtime route: live rules list and a
  refetch nudge to the role's holders), `access_changed` after commit, the catalogue port.
- **Elsewhere:** licensing `Feature.FIELD_ACCESS` in Professional (lane C owner, lane B review);
  metadata `field_marks`; work_items registers each type's custom fields; audit action
  `role.field_access_changed`; labels en/ar/ur.
- **Tests:** domain (clearest wins, a role held twice, API key keeps its owner's access, cache
  form), db (lifecycle with versions, audit and events; refusals; next request incl. a role
  held through a group; the effective view agreeing with every person's compile; licence lapse;
  the 2,000 cap; RLS), the 0162 up/down/guard test.
- **Next:** slice b (redaction, write checks, search fail-closed, `restricted` on live channels,
  built-in fields and the root_cause/view_costs gates applied after the compile, the API-key
  end-to-end test once a read path enforces), then slice c (editor UI, lane C reviews).
