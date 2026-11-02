### 2026-11-02 — WP-033 session 4: knowledge on incidents (lane C)

- Built to D-121 (plan ~/Desktop/wp-033-s4-plan.md with lane A's and lane B's conditions), stacked
  on 3b (`feat/wp-033-s4` on `feat/wp-033-s3b`), draft #153. Migration 0048.
- **Records port** `app/shared/records`: what other modules may ask about a record, answered by its
  owner with its own read rule. work_items registers it for incidents (`visible`, `summaries`,
  `requester_of`, `resolution_of`) with exactly the rule of `GET /incidents/{id}` (scope incl.
  own, trash hidden), at most 500 IDs. Requesters hold no `incidents.view` today, so they see
  nothing through it until the portal (WP-028/034) gives them their own incidents.
- **Links** (`kb_record_links`, RLS): link, unlink, the article's Links tab and the incident's
  Knowledge card in the side panel; both ends always checked; the hidden end counted ("N
  restricted"). Events `knowledge.link.saved/removed` on `kb:{id}` and the incident's `wi` channel.
- **Apply to a reply:** the editor's `extraTools` (packages/ui) and a `KnowledgeSlot` context the
  incident page provides; the reply, note and resolution editors only pass it on. The picker asks
  the server (`apply-check`) before a public insert and warns when the people the record is for
  cannot read the article. Content inserts copy the article's images into the technician's drafts
  (`copy_to_drafts`, lane B's seven conditions; `files.copied_from`, source `knowledge`); the
  composer attaches them to the reply as it does pasted images.
- **Save as knowledge:** a draft from the incident's subject and resolution, linked
  (`created_from`); the last topic used pre-selected (browser convenience); a personal-data check
  (e-mail, phone, account number, password; Arabic-Indic digits) names findings, never blocks.
- Tests: DB (port rule incl. tenant B and out-of-scope, links both ways, RLS, apply check both ways,
  copies: foreign file 404, infected named, not_scanned rescanned, sha256 mismatch leaves no
  object, quota, thumbnail, draft only for its author, requester reads the copy only through the
  saved reply; save as knowledge; 0048 up and down); domain (personal data); Vitest (picker
  warning both ways, private note asks nothing, card live refetch, save dialog); e2e written
  (warning both ways, insert, card, Links tab, axe), run in the batched QA round.
- Not in s4: the requester-side e2e (portal, WP-034); copying images from a resolution into a
  new article (the dialog says so); blocking copies after a later infected verdict on the source
  (copied_from recorded for it).
