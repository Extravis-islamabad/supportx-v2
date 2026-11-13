### 2026-11-13 — Lane B polish 8

- `organization.site_names(session, ids) -> {id: name}`: the public, read-only, tenant-scoped (RLS)
  lookup of sites' names, so lane C's new-device notice can name a mapped site instead of "a
  mapped site" (the coordinator's request). Unknown IDs are absent; a removed site keeps its name.
  Test: tests/db/test_site_names.py (own tenant, another tenant, unknown, removed).
