# SupportX v2

[![CI](https://github.com/devhat-pm/supportx-v2/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/devhat-pm/supportx-v2/actions/workflows/ci.yml)
[![Security](https://github.com/devhat-pm/supportx-v2/actions/workflows/security.yml/badge.svg?branch=main)](https://github.com/devhat-pm/supportx-v2/actions/workflows/security.yml)

Greenfield enterprise ITSM / ESM platform by Extravis: full ServiceDesk Plus capability parity, then
beyond. It ships as one codebase for SaaS, on-prem and air-gapped, with real-time updates on every screen.

> Status: Stage 0 (Foundation). See `docs/PROGRESS.md`. Local dev stack: `docs/dev-setup.md`.

## Where to start

| Path | What it is |
|---|---|
| `CLAUDE.md` | Engineering rulebook (stack, layout, non-negotiable rules, definition of done) |
| `docs/specs/architecture.md` | Architecture v0.2, the source of truth |
| `docs/specs/product-plan.md` | Product planning v0.1 (subordinate to architecture) |
| `docs/DECISIONS.md` | Product owner decision log |
| `docs/adr/` | Architecture Decision Records |
| `docs/PROGRESS.md` | Work packages, current status, session log |

## Planned layout

`backend/` (Python 3.12, FastAPI), `frontend/` (pnpm workspace, React 18 + TS), `deploy/`
(Helm, dev Compose), `licence-core/` (Rust), `docs/`.

## Prerequisites (dev)

git, uv (provides Python 3.12), Node 20+ with pnpm (via corepack), Docker with Compose, kubectl,
and k3d (D-003).
