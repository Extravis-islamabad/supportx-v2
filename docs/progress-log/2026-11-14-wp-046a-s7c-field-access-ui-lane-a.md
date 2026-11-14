# 2026-11-14 — WP-046a S7 slice c: the field access editor (lane A)

ADR-047 slice c, plan approved by lane C with UI conditions (one save model per tab, a Modal for
"Who sees this", `RestrictedValue` in packages/ui, "No rule" for the empty mode).

- `RestrictedValue` and `restrictionOf` (packages/ui): records, problem analysis fields and
  incident list cells say "Not shown to you" or "Masked" (en/ar/ur).
- Role editor: Permissions and Field access tabs for saved roles; `fieldAccess.ts` hooks in
  api-client (catalogue, rules, effective, set with Idempotency-Key and If-Match).
- Realtime: `access.changed` refetches every active query (rule c).
- `read_only_fields` (#510) removes editors on incidents and problem analysis.
- e2e `field-access.spec.ts` (live hide on an open record, axe); Visual matrix screens
  `admin-roles-field-access` and `-who`; admin guide `docs/guides/field-access.md`.

Found on the way: #510, a D-053 handover returned the record without the writer's field rules
(fixed, guard test added; lane B approved, merged).

Not done here: the Visual matrix has no Urdu column (en/ar only), so there are no Urdu shots yet
(asked lane C how they want them); a record with a live rule is shot by the e2e journey in
English, not by the matrix (it needs a rule in place).
