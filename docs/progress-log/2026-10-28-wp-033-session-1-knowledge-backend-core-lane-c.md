### 2026-10-28 — WP-033 session 1: knowledge backend core (lane C)

- Knowledge module (D-108): settings, article types (file 08 Appendix A defaults on first use),
  topic tree (six levels, move with subtree, delete moves the articles first), articles with a
  first draft, autosave with If-Match, one open draft per language, new version from the
  published one, translations. Migration 0036 with RLS on all five tables; a trigger keeps
  published and superseded versions unchanged (REQ-KB-020 AC2).
- Permissions: the 11 D-108 (7) permissions, declared by the module with role defaults
  (technician: view/create at group, edit own and submit at own; requester: view at own). The
  reserved `knowledge.view`/`knowledge.manage` left identity's list (lane B told); custom roles'
  `knowledge.manage` becomes create + edit own + submit. That data step runs once per tenant
  with app.tenant_id set, because FORCE RLS hides every row from a migration without it. The
  same issue was found in 0034 and lane A fixed it (#116).
- Who reads what: staff by technician audience (all or their groups); drafts only for the
  author, owners and approvers; requesters get nothing from staff paths (their portal reading
  is session 2). Lists, single reads and search share one predicate (REQ-KB-048).
- Rich text: `div[data-callout]` with the four callout kinds is kept by the sanitiser.
- Bug found by the tests: changing only the expiry date skipped the review/expiry check, so
  the database constraint answered with a 500. Fixed in the service.
- Not in this session (sessions 2-4 per D-108): review and approval, publish/withdraw,
  requester portal reading, attachments (files owner type with lane B), console and portal
  screens, knowledge-manager role seed, department audiences for requesters.
