### 2026-11-04 — WP-031 session 1: service catalog administration, backend (lane A, D-138, ADR-039)

- Category tree (four levels, no loops). A disabled category hides its items from requesters.
  A category with items or subcategories is never deleted.
- Items are drafted, published, retired and published again, by hand or at a planned time (a
  schedule every minute, audited). An item that became incomplete stays a draft. Copy makes a
  draft "Copy of …". An item with requests is retired, never deleted.
- Publishing needs an English name, a category and a fulfilment group. Managers see the
  translations still missing.
- Forms gain ten question kinds, choice words per language, help text, defaults, and who sees
  each question. Requesters never see or answer the technician's or approver's questions. A
  subject template fills a request's subject from the answers.
- "Report a problem" entries point at an incident template marked for requesters.
- Search over names, keywords, summaries and descriptions in English, Arabic and Urdu, with
  spelling variants and typos. 1,000 items answer within 500 ms (p95, tested). ADR-039: the
  catalog stays on PostgreSQL up to 10,000 items per tenant.
- The starter catalog (D-138): 6 categories and 14 items in three languages, seeded as drafts
  when a tenant is provisioned (new event `organization.tenant.provisioned`), once per tenant.
  An admin chooses the group and publishes them in one step. Existing tenants get it only with
  `make catalog-starter`.
- Migrations 0073 and 0074 (the second changes existing data: full-ci).
