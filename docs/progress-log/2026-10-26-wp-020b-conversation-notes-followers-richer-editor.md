### 2026-10-26 — WP-020b: conversation, notes, followers, richer editor

- **Built:** see the WP-020b entry. Decisions D-079 (defaults) and D-080 (Tiptap mention and
  suggestion, MIT). ADR-026 amended (followers and shared reach). Migration 0016 on top of 0015.
- **New dependencies:** `@tiptap/extension-mention`, `@tiptap/suggestion` (MIT, 3.31.4; D-080).
- **Shared changes:** `ResourceType.shared_scope`/`shared_actions` in the policy layer;
  `EmptyText` in `@supportx/ui`; sanitiser allow-list (span/mark with palette codes, alignment and
  indent codes, mentions); e2e teardown also removes the suite's conversation rows.
- **Tests:** backend 972 passed, 1 skipped, 94.57 %; new `test_conversation_api.py` (18, incl.
  RLS for the three tables) and domain tests; console 83, ui 45 (editor and Word paste); e2e
  incident journeys 3/3 locally (hand-over now keeps following, then unfollow removes access).
- **Chrome check before the PR** found and fixed four UI bugs: the text-style picker stretched the
  toolbar onto three lines in forms; mention list unreadable in dark mode (mounted outside the
  theme); the record page left a quarter of the screen empty (fixed 1200 px cap, also on the create
  form); the disabled Reply button's arrow looked active; the empty editor's placeholder sat on the
  left in Arabic. Known, not fixed: the first pasted paragraph takes the alignment of the empty line
  it lands in (ProseMirror merges them).
- **Dev environment:** dev database migrated 0013 → 0016 (forward only); fan-out, consumer workers
  and the console dev server restarted to load the new code and dependency.
