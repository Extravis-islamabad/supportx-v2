# ADR-030: Custom fields — definitions in the metadata module, typed JSON values, indexes on request

- **Status:** Accepted
- **Date:** 2026-10-27
- **Source:** WP-026; architecture.md §6.6 (metadata-driven customisation), §7.1, §10; docs/specs/parity/01-work-items-incidents.md REQ-INC-014; D-086, D-087
- **Owner:** Haider (Product Owner)

## Context

REQ-INC-014 asks for admin-defined fields of many types that "work like built-in ones in forms,
lists, filters, rules, reports, exports and the API", with labels and help in each language, a
key never shown to users (AC3), promotion of a frequently filtered field to an index without a
code change (AC2), and removal of a field in use that keeps its old values in history (AC4).
architecture.md §6.6 already chose "custom field values in typed JSONB with GIN indexes". Every
later module (problems, changes, service requests, assets) needs the same thing.

## Decision

1. **Definitions in the `metadata` module** (`custom_fields`, one row per tenant, entity and
   key; RLS like every business table). Other modules use its public interface only:
   `definitions`, `clean` (type checks, validation, required rules, people exist),
   `mark_used`, `filter_fields` and `text_for_search`. Adding an entity is a new enum value and
   its table name, not new code paths.
2. **Values on the record** as typed JSON by key (`work_items.custom`): numbers as JSON numbers,
   dates as ISO dates, date-times in UTC, multiple choices as arrays. A GIN index
   (`jsonb_path_ops`) serves containment; history records each value as `custom.<key>`.
3. **Filters through the shared DSL** as `custom.<key>`, typed per field. The SQL of each value is
   one literal expression with guarded casts (`CASE WHEN jsonb_typeof(...) = 'number' THEN ...`),
   so another tenant's same key with another type never makes a query fail. Keys are validated
   (`^[a-z][a-z0-9_]{1,39}$`) before they are put into SQL.
4. **Indexes on request, built by the migration job.** The admin's request only marks the field.
   `tooling.custom_field_indexes` (run by each deploy's migrate Job, or by hand) creates an
   expression index with CREATE INDEX CONCURRENTLY as the migrator role, using the very same
   expression text the filters use, so PostgreSQL can pick it. One index per key and type serves
   every tenant with that key and type; a failed build is dropped and recorded as failed. The API
   role never runs DDL.
5. **Search text kept on the record.** The free text of text-like fields is written to
   `work_items.custom_text` on every save; the search port (WP-027, D-085) reads it. A generated
   column cannot do this, because it cannot read the field definitions.
6. **Keys are permanent.** Removing a field soft-deletes the definition; its key is never given to
   another field, so old values and history never change meaning.

## Consequences

- One mechanism for every module; reports and exports read the same definitions.
- An index exists only after the next job run (minutes in SaaS, the next deploy or a manual run
  on-prem); the admin screen shows "requested", "active" or "failed" live.
- Values of a removed field stay in the JSON. They are not shown or filtered, and their search
  text goes on the record's next save.
- Index names are bounded by PostgreSQL's 63 characters (`ix_cf_<entity>_<type>_<key>`).
