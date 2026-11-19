### 2026-11-19 — WP-046b S3a: favourites, unread rows, row colours and D-176 view sharing (lane A)

#549, merged 2026-11-18 (migration 0178 on 0180). The plan was approved by the coordinator;
D-176 holds Haider's answers. Lane C blocked under D-175 (in-module permissions, encryption) and
read the console with the Visual matrix.

- **0178:** `work_item_view_favourites` and `work_item_reads` (tenant first in the primary key,
  RLS forced, personal, removed by erasure); `work_item_views.unshared_at` and `unshared_field`;
  `row_colour_by` on type settings and list settings. No data step.
- **Favourites** (REQ-INC-107 AC1): PUT/DELETE `/saved-views/{id}/favourite`, starred first.
- **Unread** (REQ-INC-115 AC2): `reads.unread_ids` on every list page, `POST /{id}/read` from the
  record page. A reply does not move the record's version, so public entries are checked on
  their own; a record never opened counts only for its assignee.
- **Row colours** (AC1): `GET/PUT /settings/list-display` (audited), a person's choice in list
  settings; the console's `readableMark` keeps the mark at 3:1.
- **D-176:**
  - `share_views` and `share_views_wide`, checked for what a save adds;
  - the read-time check (`lists.usable`), the guarantee;
  - the save-time 422 on a restricted or sealed filter;
  - the view audit (`view_audit`: a six-hourly schedule, on field rule and seal changes, and on
    request; audited) with the owner's notice and the administrators' report.
  - Releases: the release manager shares (technicians keep view only, WP-058).
- **Console:** the star, the Starred group, unread bold with a dot and a spoken "Unread", the row
  mark, the share picker limited to what the person may do, the General tab's row colour and
  view audit cards, and links that open a view.
- **CI found four misses after review** (all fixed): the audit re-run POST was not audited, the
  route map was stale, a notification area label was missing, and an RLM written as an escape
  sat in an Urdu label. Since then `make route-permissions` and the label tests run before every
  push.
- **Follow-ups:** sealed filter values in stored views (lane C's decision; the next PR); the hex
  pattern on the admin colour fields; the unread dot kept inline (lane C's polish).
