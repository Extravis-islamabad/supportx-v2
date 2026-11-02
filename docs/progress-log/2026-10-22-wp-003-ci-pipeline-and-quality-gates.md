### 2026-10-22 — WP-003 CI pipeline and quality gates
- Recorded D-015..D-017 (private GitHub repo + Actions, S3-only object storage, Temporal without
  auto-setup); ADR-012 updated with the object-storage direction and the MinIO image situation;
  WP-014 notes added. Later D-018: the repo is temporarily public because of a billing block.
- Created https://github.com/devhat-pm/supportx-v2 (private), pushed full history.
- `.github/workflows/ci.yml` (backend, frontend, pre-commit jobs), `security.yml` (gitleaks over
  full history, pip-audit + pnpm audit, Trivy fs; weekly), `stack-smoke.yml` (core profile +
  `make dev-check`; on compose PRs and nightly). Jobs call Makefile targets; composite actions
  `setup-backend` / `setup-frontend` share the toolchain setup (uv cache, pnpm store cache).
  Actions pinned to commit SHAs; `permissions: contents: read`; concurrency cancels stale runs.
- New Makefile targets `precommit`, `audit` (`audit-backend`, `audit-frontend`).
  `backend/tooling/vuln_gate.py` adds the high/critical gate pip-audit lacks (GHSA severity
  lookup; unknown severity blocks), with tests; proven to fail on jinja2 2.10 (1 high).
- Dependabot (actions, uv, npm; weekly; minor/patch grouped), PR template (DoD checklist),
  CODEOWNERS (`@devhat-pm`).
- First runs were refused by GitHub billing; after the switch to public: CI, Security and Stack
  smoke green on main, CI and Security green on PR #1 (README badges), PR #1 merged. Branch
  protection refused while private (403, needs Pro); applied once public.
- Follow-ups: Trivy misconfig scanning only covers files Trivy knows (no compose); Dependabot
  `docker-compose` ecosystem could track the pinned dev images (not requested; suggest later).
