### 2026-10-26 — WP-022 review follow-ups (lane B)

- D-084 recorded: the admin "rotate data key" action is V1; new enum values are additive, and
  API clients must tolerate unknown enum values (`docs/architecture/api-conventions.md` §8).
- Urdu labels for every licence limit (`limit.*`), with a test that every limit has Arabic and
  Urdu.
- Flaky console announcements test, cause found: `pnpm test` ran four packages at once, each
  Vitest with a worker per CPU core, so about four jsdom workers per core. A file's first full
  render (about 1.5 s of CPU, measured with a CPU profile: Ant Design styles parsed by jsdom
  and React's first render) then sometimes ran past the 5 s test limit, about one run in five.
  Fix: `pnpm test` runs the packages one after another (`--workspace-concurrency=1`): 6 of 6 runs
  green, and faster (about 35 s against 40–70 s). Preloading the lazy routes was tried and did
  not help (the time was not module loading).
- D-085 recorded: PostgreSQL full-text search with pg_trgm for MVP, behind a search port
  (ADR-029 comes with WP-027).
