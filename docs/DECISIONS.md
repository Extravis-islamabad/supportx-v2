# Product owner decision log

Decisions made by the product owner that change or clarify the specs. Architecture-level choices
still live in `docs/adr/`; this log records *who decided what and where it was applied*. Specs,
ADRs and CLAUDE.md must be kept consistent with this log.

**Each decision is its own file in [`docs/decisions/`](decisions/)**, `D-NNN.md` (D-123). This
page stays fixed, so lanes no longer collide on one shared table. `make decisions` writes the full
table to `docs/_build/DECISIONS.md` (not committed).

## Adding a decision

1. Take the next free number on the latest `main` (and in `docs/LANES.md`'s claimed column).
2. Create `docs/decisions/D-NNN.md`:

   ```markdown
   # D-NNN (YYYY-MM-DD)

   ## Decision

   What was decided, by whom (product owner, or through the coordinator).

   ## Rationale

   Why.

   ## Affected docs

   CLAUDE.md §3, PROGRESS.md (WP-0NN), ...
   ```

3. `cd backend && uv run pytest tests/test_docs_entries.py` checks the format. Two lanes taking the
   same number now conflict on the file itself: the later lane renumbers (LANES rule 4).

Never edit an existing decision's meaning: a change of mind is a new decision that names the old
one (as D-038 does for D-004).
