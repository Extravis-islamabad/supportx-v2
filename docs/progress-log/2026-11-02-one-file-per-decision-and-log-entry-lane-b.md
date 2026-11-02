### 2026-11-02 — One file per decision and log entry (lane B, D-123)

- Moved the 117 decisions from the `docs/DECISIONS.md` table into `docs/decisions/D-NNN.md`, and
  the 78 session-log entries from `docs/PROGRESS.md` into `docs/progress-log/`. The text is
  unchanged: the rendered table matches the old rows, now sorted by number.
- `backend/tooling/docs_entries.py` with `make decisions` and `make progress-log` (output in
  `docs/_build/`, ignored by git); `tests/test_docs_entries.py` checks format, unique numbers, and
  that `DECISIONS.md` and `PROGRESS.md` hold no entries again.
- Open: CLAUDE.md §1 and §11.8 still say "the decision log" and "newest-first session log entry"
  in `PROGRESS.md`; the product owner decides the wording.
