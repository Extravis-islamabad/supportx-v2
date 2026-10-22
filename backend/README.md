# backend

SupportX v2 Core API (FastAPI modular monolith) and workers. Python 3.12, managed with uv.
Layout and rules: architecture.md §6 and `CLAUDE.md`. The module contract is in
`app/modules/README.md`.

```bash
uv sync                      # create .venv with Python 3.12 (never the system Python)
uv run pytest                # tests + coverage
uv run ruff check . && uv run ruff format --check .
uv run mypy                  # strict
uv run lint-imports          # module boundary contracts
```
