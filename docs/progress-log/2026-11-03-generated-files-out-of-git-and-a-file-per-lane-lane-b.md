### 2026-11-03 — Generated files out of git, a file per lane (lane B, D-127)

- `openapi.json`, `schema.ts` and the backend `resources.json` are ignored; `make generated`
  (also in `make setup`) writes them, the frontend scripts write them when missing, CI writes
  them in every job that needs them (`.github/actions/generated`), and both image builds refuse
  to start without them (offline, nothing generated inside).
- The OpenAPI diff exports the target branch's contract from its code (a target branch from
  before D-127 still has its committed copy, which is used then).
- Tests that read the committed copies now build what they need: the enum-label test builds the
  schema in-process; the label export test runs the export script into a temporary file.
- `docs/LANES.md` is the index, the QA lock and the rules; `docs/lanes/A.md`, `B.md`, `C.md` each
  hold one lane's row, checked by `tests/test_docs_entries.py`.
- Checked locally from a clean state (the three files deleted, then `make generated`):
  frontend lint, typecheck and labels tests, backend lint and the affected backend tests.
- Open: CLAUDE.md §3 still says CI fails when `schema.ts` is out of date; the product owner
  decides the wording.
