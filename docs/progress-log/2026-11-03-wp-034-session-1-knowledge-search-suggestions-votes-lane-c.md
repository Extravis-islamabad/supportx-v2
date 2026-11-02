### 2026-11-03 — WP-034 session 1: knowledge search, suggestions, votes (lane C)

- Built to D-125 (plan ~/Desktop/wp-034-plan.md), draft #158 on WP-033's branch (#157).
  Migration 0050 (kb_votes, featured, the two settings, the topic-name search function).
- **One visibility rule everywhere:** search, suggestions, "popular" and the portal's reads are
  the article list's own query; a test proves a hidden article is in none of them for a reader
  outside its group or a requester, and in all of them for its group.
- **Search (REQ-KB-053):** topic names, typos (pg_trgm), highlighted snippets as text and marks
  (never HTML), filters audience, updated from/to, featured, popular order; found in the same
  transaction that publishes it. Knowledge in the command palette beside incidents.
- **Suggestions (REQ-KB-062, REQ-INC-021):** `GET /knowledge/suggestions` (any word, published,
  the reader's rule). On the new incident form a fixed 320 px column suggests while typing
  (400 ms pause) and never moves the form; chosen articles are linked after the create with
  source `suggestion`. Admin › Knowledge: "Suggest articles while technicians log an incident".
- **Did this help? (REQ-KB-069):** one vote per person and published version, changed in place;
  a "no" may give a reason and a comment; scores and feedback (never who) for editors and
  approvers on the Feedback tab, live; a new version starts at zero.
- **Portal reads (REQ-KB-081):** topics with readable articles and their counts; recent,
  popular and featured lists; 404 to requesters while requester knowledge is off.
- Fixed on the way: list filters compared columns with None when a filter was unset (every list
  call failed once a filter param existed).
- Tests: DB (search, filters, the hidden-article rule, suggestions, votes, kb_votes RLS, portal
  reads, the setting and link source; 8), console Vitest (votes, Feedback tab, suggestions on
  the form, palette), e2e `knowledge-search.spec.ts` written and typechecked (palette, live
  vote count, suggestions beside a form that does not move, axe), run in the batched QA round.
- Still in this WP: the knowledge screens on the console layout of D-124 once #159 is on main;
  session 2 (portal pages) after WP-028.
