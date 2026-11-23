### 2026-11-14 — WP-046a S7 slice b1: field access enforced on reads and writes (lane A)

- **Reads:** one rule set per record (`work_items/domain/field_access.py`: role rules, then the
  older permission gates, which always win); the record, list, search and duplicate rows and
  the history withhold hidden and masked fields (null, named, custom values left out).
- **Filters and reports:** the shared `list_query` gains an opt-in `exclude_for`; work items
  drop withheld fields from the list allowlist, list-fields and the report source.
- **Writes:** `require_writable` on edit (really changed fields only), on create (the person's
  own input, before form rules) and so per bulk item; 403 `field_read_only`; service identities
  exempt (`Subject.person`, cached).
- **Catalogue:** built-in fields join (impact details; the problem's analysis and review texts).
- **Tests:** db (record, list, history, create, edit, filter and sort, report, an API key end to
  end), domain (the older gate wins, read-only, core fields never offered).
- **Not done:** a 10k-row timing check (a page is at most 200 rows; redaction is one dict filter
  per row). Bulk result rows carry codes and field names, never values (checked, no change).
- **Next:** b2, then slice c.
