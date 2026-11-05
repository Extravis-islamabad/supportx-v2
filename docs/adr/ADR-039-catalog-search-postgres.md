# ADR-039: Catalog search in PostgreSQL, not OpenSearch

- **Status:** Accepted (coordinator for the product owner, 2026-11-04; WP-031 plan D12, D-134)
- **Date:** 2026-11-04
- **Deciders:** Haider (Product Owner), lane A

## Context

REQ-CAT-028 asks for search across the catalog: names, summaries, descriptions, keywords and
synonyms in every tenant language, typos tolerated, Arabic and Urdu spellings normalised, ranked
by relevance, never showing an item the person may not request. The stack names OpenSearch for
search (architecture.md §5), and ADR-029 already put record search (WP-027) on PostgreSQL behind
the shared search port, with OpenSearch as a later adapter.

A catalog is small and changes rarely: tens to a few hundred items per tenant, a thousand in a
large one. Who may see an item depends on its status, audience and category tree, which the
catalog already decides in SQL (`offered`).

## Decision

1. **Catalog search uses the shared search port (ADR-029) on the PostgreSQL engine.** Full-text
   (simple, English and Arabic configurations) plus `pg_trgm` word similarity, with the shared
   normalisation (`sx_search_normalize`: Arabic and Urdu letter variants and diacritics).
2. **The searchable text lives in the item's own generated columns** (migration 0073):
   `search_vector` (names, keywords and summaries weighted A, descriptions with HTML stripped
   weighted B, every language) and `search_name` (names and keywords, normalised, for typos),
   with GIN indexes. Always current, in the same transaction as the row.
3. **Search starts from the query that lists the viewer's items**, so visibility (status,
   audience, disabled categories, RLS) is applied in SQL. Nothing is copied into an index.
4. **The budget is tested:** p95 ≤ 500 ms for 1,000 items through the API
   (`tests/db/test_catalog_admin_api.py`).
5. **When to move to OpenSearch:** if a tenant's catalog passes **10,000 live items**, or the
   p95 test fails at the sizes customers run, the OpenSearch adapter replaces the engine behind
   the same port (ADR-029). The scope filter stays in PostgreSQL either way.

## Consequences

- No OpenSearch dependency for the catalog: the same search on SaaS, on-prem and air-gapped.
- Popularity ("most requested") is not yet part of the ranking: ties go to featured items, then
  the catalog's order. WP-032 adds request counts for the portal home.
- Urdu has no stemmer anywhere; it matches by word prefix, as in ADR-029.
