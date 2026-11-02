### 2026-10-24 — Parity spec phase 1 (docs only)

- Added `docs/specs/parity/`. `README.md` is the index: 14 modules in build order with their
  ID prefixes and the reference areas each draws on; the ID scheme; the fields every
  requirement has; how acceptance criteria become test names; and the cross-cutting lessons,
  each mapped to the requirement that implements it.
- Added `01-work-items-incidents.md` with 173 requirements: 24 engine-wide (REQ-WI) and 149
  for incidents (REQ-INC).
  - By decision: 89 SAME, 60 BETTER, 22 NEW, 2 SKIP.
  - By priority: 84 MVP, 73 V1, 16 LATER.
  - It also holds proposed tenant defaults (Appendix A) and 12 open questions.
- Gaps: reference Area 14 is not in the repo (the brief named Areas 1–14), and ESM has no
  research area. Neither blocks file 01.
- No code changed. Next phase: file 02 (service requests, catalog, portal).
