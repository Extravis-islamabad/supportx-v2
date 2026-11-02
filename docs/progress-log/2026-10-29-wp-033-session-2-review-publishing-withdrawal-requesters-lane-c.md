### 2026-10-29 — WP-033 session 2: review, publishing, withdrawal, requesters (lane C)

- Built to the approved plan (~/Desktop/wp-033-s2-plan.md). Submit, approve and reject (reason
  required, shown on the author's draft), self-approval per the setting (REQ-KB-027, 028).
  Approval replaces the published version in the same transaction, so readers keep version N
  until N+1 is approved (REQ-KB-021). Withdraw with a reason leaves every reader path (page,
  lists, search, files); a reader on an old link gets "no longer available" (REQ-KB-031).
  "Still correct" records a review and moves the date with no new version (REQ-KB-034). Trash
  and restore (REQ-KB-079), versions list, the views (published, my drafts, in review, awaiting
  my approval, review due, expired, trash), the approval count, settings with If-Match.
- Requesters read published, unexpired, unwithdrawn articles in their audience (all, or their
  groups, sites or department), and nothing while requesters are switched off (REQ-KB-045,
  048, 090). API only; the portal pages are WP-034.
- Notifications through the shared port (REQ-KB-086): submitted to the approvers (the topic
  owner and anyone whose approve scope covers the article); approved, rejected and withdrawn
  to the author and owner; review due to the owner, from an hourly sweep that reminds once per
  review date. Requesters never get review notifications.
- Realtime: staff list channels get IDs only for the article's audience; readers refetch on a
  tenant broadcast that names nothing (REQ-KB-048 AC3).
- Migration 0041 (after lane A's 0039 and 0040; renumbered at merge if needed): `kb_reviews`
  with RLS, `kb_articles.review_reminded_on`, and the files owner type `kb_article`; knowledge
  registers its file access (the same reader rule).
- Not in this session: permanent delete (hard deletes only through GDPR erasure jobs, CLAUDE.md
  §6); the knowledge-manager role grants (lane B adds the role key; the grants follow once it is
  on main); the article page's record channel (session 3 screens); console screens (session 3);
  portal pages (WP-034); incident links (session 4).
