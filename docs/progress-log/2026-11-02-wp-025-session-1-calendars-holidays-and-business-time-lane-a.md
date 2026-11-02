### 2026-11-02 — WP-025 session 1: calendars, holidays and business time (lane A)

- Re-oriented after the laptop shutdown; all lane A PRs green and marked ready (#120, #140-#144,
  #146; #145 stays a draft until #120). Cross-lane reviews posted on #126, #135 and #138.
- Built WP-025 session 1 on `feat/wp-025-s1` (#148, stacked on #144): see the WP-025 section.
  Migration 0044 (lane B holds 0042/0043, lane C 0041; the queue settles the chain).
- Choices made inside the approved plan (for the product owner to confirm, see the PR): a half
  day off splits the day's **working time** in half (09:00-18:00 at 13:30); a holiday removes
  the periods that **start** on its date (a night shift starting the evening before still runs);
  a local time inside a spring-forward gap takes the offset from before the change.
- Checks: SLA domain 130+ and API/DB 22 tests pass; console 336, api-client 12, labels 37;
  migration and RLS guard pass; ruff, mypy, import-linter (sla contract added), tsc, ESLint,
  Prettier clean. Full `make check` not run (rule: CI and the queue run it).
- Next: auto-close on business time after #140 lands; then session 2.
