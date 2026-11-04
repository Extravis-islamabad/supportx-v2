### 2026-11-05 — WP-058a session 1: the stage engine and the release record (lane C)

- **ADR-041 (proposed):** one stage engine for releases and changes.
  - Revised after lane A's review, with their five additions: `lifecycle_version` on records,
    `required_fields` on transitions, RLS with tenant-carrying keys, cancel's role rule in the
    guard, and `stage_changed`'s from and to stage and entry id.
  - Items 5 and 6 of lane A's second review are recorded for session 3.
- **Engine:**
  - Every move is a listed status-to-status transition. Reaching a stage's one completing status
    moves on to the next stage in the same save.
  - Approval outcomes are set only through `system_stage_move`.
  - Paths have optional stages. Disabled paths keep working for the records already on them.
  - Moves run the closing rules by category, the in-transaction rules and the transition's
    required fields.
  - Stage entries are never rewritten.
  - The rail is computed: after going back, later stages are future again.
  - History covers status and stage. Each move emits the status event (`stage_move`) and
    `work_items.work_item.stage_changed`.
  - Types register a StageGuard.
- **Releases:** a live type (REL prefix) with file 06 Appendix A seeds: 9 stages, 27 statuses,
  default and emergency paths, cancel and reopen as seeded moves.
  - `GET /releases/{id}/stages` returns the rail and the offered moves.
  - `POST /releases/{id}/moves` makes a move and needs If-Match.
  - `GET/PATCH /releases/{id}/details` holds the release's own fields:
    - type and reason from the type's own pick lists;
    - risk, with a reason in history;
    - version and build, both searchable;
    - sanitised notes;
    - scheduled and actual dates, with an end never before its start;
    - release manager and engineer.
- **Permissions:** identity's reserved `releases.*` keys move into work_items (lane B reviewed).
  - Technicians keep only `releases.view`.
  - 0091 maps saved `releases.manage` grants to the engine's actions. Its downgrade refuses
    rather than lose a grant.
- **Migrations:** 0090, 0091 and 0092 (numbers from the coordinator). 0090 is re-pointed to 0074
  after #200.
  - 0092 widens two shared checks from their live definitions, so either landing order with
    lane A's problem lists keeps both.
- **Tests:**
  - Releases API: 16, including RLS on all six new tables.
  - 0091 up, down and refused-down: 3.
  - Permission pins: 3.
  - Stage domain: 9.
  - Migrations and guard: 13.
  - Label checks: all green.
- **Also this session:**
  - #213 (WP-038 session 2) and #215 (the CLAUDE.md pg_trgm line, confirmed by Haider in lane
    C's window) merged.
  - The first full Visual matrix run on main failed shard 5 on a test bug (late route handlers);
    the fix is #217.
