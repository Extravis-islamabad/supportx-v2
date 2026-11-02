### 2026-10-22 — WP-001 monorepo skeleton and dev tooling
- Backend: uv project pinned to Python 3.12 (`.python-version`), FastAPI app factory with
  `GET /api/v1/health`, §6.4 package layout, ruff (`select = ALL`), mypy strict, pytest +
  pytest-asyncio + coverage (fail-under 90%), import-linter with a custom `module_boundaries`
  contract (`backend/tooling/import_contracts.py`) plus a layers contract. 8 tests pass, 100% coverage.
- Frontend: pnpm workspace (`frontend/`), console + portal (Vite 8, React 18.3, TS 5.9 strict,
  Ant Design 5.29 with light/dark tokens, RTL switch, language picker), packages ui, labels
  (humanize, label lookup, en/ar/ur resources), plus placeholder api-client, realtime, charts, forms
  and flow. ESLint 10 flat config (typescript-eslint strict type-checked), Prettier, Vitest 5.
  18 tests pass. Both production builds succeed (chunk-size warning, ~607 kB / 194 kB gzip).
- Root: Makefile (setup, lint, typecheck, test, format, check, build), pre-commit (large files,
  ruff, ruff-format, mypy, eslint, prettier), `tsconfig.base.json`, `.prettierrc.json`, `.nvmrc`
  (24). Placeholder READMEs in `licence-core/`, `deploy/`, `mobile/`.
- `make check` green. Follow-ups: route-level code splitting (WP-010/WP-015); copyright-header
  policy (ruff CPY001 disabled for now).
