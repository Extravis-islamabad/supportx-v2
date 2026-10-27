# ADR-030: Custom fields — definitions in the metadata module, typed JSON values, indexes on request

- **Status:** Accepted
- **Date:** 2026-10-27
- **Source:** WP-026; architecture.md §6.6 (metadata-driven customisation), §7.1, §10; docs/specs/parity/01-work-items-incidents.md REQ-INC-014; D-086, D-087, D-088
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
4. **Indexes on request, built by a dedicated index worker** (D-088). The admin's request marks
   the field "pending". The index worker (`workers.custom_field_indexes`, its own Deployment)
   looks every 30 seconds, marks the fields "building" and creates an expression index with
   CREATE INDEX CONCURRENTLY as the migrator role, using the very same expression text the
   filters use, so PostgreSQL can pick it. Every expression is immutable (dates and times are
   built with make_date / make_timestamp ... AT TIME ZONE 'UTC', never `::date`, which depends on
   session settings). One index per key and type serves every tenant with that key and type. An
   advisory lock keeps one builder at a time; a field left "building" by a stopped worker is built
   again on the next pass. A failure is recorded as a reason code (SQLSTATE mapped: timed out,
   busy, disk full, out of memory, value too large, unexpected) and its INVALID index dropped; the
   database's own text goes only to the log. The deploy's migrate Job runs the same pass as a
   fallback. Only the table owner may create an index and a concurrent build cannot run in a
   transaction (so not in a database function): the API and the other workers never get DDL
   rights.
5. **Search text kept on the record.** The free text of text-like fields is written to
   `work_items.custom_text` on every save; the search port (WP-027, D-085) reads it. A generated
   column cannot do this, because it cannot read the field definitions.
6. **Keys are permanent.** Removing a field soft-deletes the definition; its key is never given to
   another field, so old values and history never change meaning.

## Consequences

- One mechanism for every module; reports and exports read the same definitions.
- An index is usually active a minute or two after the request, on every deployment; the admin
  screen shows pending, building, active or failed (with the reason) live.
- One more Deployment holds the migrator credentials: the index worker. It runs nothing but
  this pass.
- Values of a removed field stay in the JSON. They are not shown or filtered, and their search
  text goes on the record's next save.
- Index names are bounded by PostgreSQL's 63 characters (`ix_cf_<entity>_<type>_<key>`).
