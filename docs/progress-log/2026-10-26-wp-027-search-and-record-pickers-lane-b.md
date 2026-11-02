### 2026-10-26 — WP-027 search and record pickers (lane B)

- Planned and built in one session in `../supportx-v2-wp027`. The product owner confirmed
  PostgreSQL full-text search for MVP (D-085) and asked for typo tolerance (pg_trgm) and a port
  ready for pgvector (ADR-029).
- Coordinated with lane A (WP-026). This WP keeps migration 0020 and ADR-029; WP-026 takes 0021,
  D-086 and ADR-030, and feeds custom-field text into the same vector.
- Found and fixed while building: an INSERT returned the generated tsvector with every new
  incident. The search columns are now `unmapped_column`s.
- Shared `useDebounced` (`apps/console/src/useDebounced.ts`) replaces two copies.
