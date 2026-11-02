### 2026-10-22 — WP-002 local dev stack (Docker Compose)
- Recorded D-012..D-014 (helper libraries + dev-helper rule, i18next for labels in WP-010,
  TypeScript 5.9.x) in `docs/DECISIONS.md` and CLAUDE.md §3.
- `deploy/compose/`: compose file with 13 services + `minio-init` one-shot, all images pinned and
  multi-arch (arm64 verified), ports on 127.0.0.1 in a 2xxxx range (5432, 6379, 4222, 8025 are
  taken by other projects on the dev Mac), memory limits on every service. Postgres init creates
  `supportx`, `keycloak`, `temporal`, `temporal_visibility`, extensions vector/pgcrypto/citext, and
  the roles `supportx_migrator` (owner) and `supportx_app` (no superuser/owner/BYPASSRLS, DML-only
  default privileges). `make dev-init` generates random secrets into git-ignored `.env`.
- `make dev-check`: 18 core checks + 7 full checks, including a rolled-back functional RLS probe.
  Results: core 18 PASS / 7 SKIP; full 25/25 PASS; restart from kept volumes 18 PASS. Verified that
  a stopped service yields FAIL + non-zero exit, and that `dev-reset` deletes nothing without "yes".
- RAM: core ≈ 0.8 GB, full ≈ 3.3 GB (docker stats). `make check` green.
- Image deviations: MinIO community images were withdrawn from Docker Hub/Quay, so dev uses
  `pgsty/minio` + `pgsty/mc` (community build, AGPL; dev only; feeds ADR-012). Temporal
  `auto-setup` stops at 1.29.7 (server is at 1.32); fine for dev, revisit in WP-014.
- Follow-ups: WP-005 must create the same two roles in Testcontainers fixtures (the init script
  only runs in this dev stack); WP-006 realm import; WP-014 must decide Temporal schema setup
  without `auto-setup`.
