### 2026-10-29 — WP-033 session 3a: knowledge console screens (lane C)

- Built to D-117 (plan ~/Desktop/wp-033-s34-plan.md), stacked on session 2 (`feat/wp-033-s3a`
  on `feat/wp-033-s2`; rebased onto main once session 2 merges).
- Backend gaps:
  - views `due_today`, `overdue` and `withdrawn`;
  - type, owner and language filters, with rows carrying the owner and the flags;
  - the article record channel `t:{tenant}:kb:{article}`, joined only by those who may read the
    article now;
  - a disabled owner's articles move to the topic owner, with history (REQ-KB-033 AC2);
  - article history for its editors, approvers and withdrawers (REQ-KB-080);
  - the owner's name on article responses.
- Console:
  - **Knowledge home:** topic tree (new, edit, move up and down, delete with "move its articles
    to"), the ten views with the live approval count, search, and type and language filters.
  - **Article page:** path, flags, language switch (Arabic right to left), contents, tabs
    (versions, history, plus links, comments and feedback as placeholders), a side panel with the
    audience in plain words, review actions that stay visible and say why when unavailable, and
    article settings (topic, type, owner, dates, own audience).
  - **Editor:** new article, and per-language drafts with autosave (If-Match), the conflict
    dialog, a leave guard, callouts (D-108 (9)) and inline images attached to the article.
- Live: lists, topics and the count refetch on the knowledge list and tenant channels; the article
  page on its own channel.
- Tests: DB tests for the channel, views, filters, hand-over and history; Vitest for the rules and
  the screens; labels in en, ar and ur.
- Not in 3a: drag-and-drop topic reordering (move up/down buttons instead), the approval inbox
  with preview, the knowledge settings page and the e2e round in English and Arabic under the QA
  lock (all session 3b).
