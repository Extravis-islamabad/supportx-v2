### 2026-11-17 — WP-046b S4: major incidents, announcing and printing (lane A)

Plan approved by the coordinator 2026-11-17 (migration 0177, after 0172/0173/0175/0176).
Lane B's conditions (print, announce port, declare major) and lane C's (the announcements port,
which lane C owns, and the UI) are in the PR description, each with the test that holds it.

- Migration 0177: `work_items.major` with when, by whom and why; the type settings' major team
  (`major_group_id`, `major_user_ids`) and `major_template_id`; `work_item_announcements`
  (tenant first, RLS, actor audit, a unique live pair).
- Services: `major_incidents` (declare, end, open majors, settings), `incident_announcements`
  (announce, linked, end); announcements' `for_records` port (`announce_for_record`,
  `end_for_record`, `announcement_states`); `set_fields(unrecorded=)` names a field in history
  without its value; the conversation timeline's `visibility` filter.
- Right: `incidents.declare_major` (service desk managers). Event `work_items.major.changed` v1
  (IDs and the flag). Audit: `incident.major_declared`, `incident.major_ended`,
  `incident.major_settings_changed`, `incident.announced`. `major_reason` is in the mentions port.
- Import contract: announcements never imports work_items.
- Console: the major dialog and marker (record and lists), the announce dialog, panel card and
  resolve prompt, the print dialog and printable page.
- Tests: `test_major_incidents` (3), `test_incident_announcements` (4), `test_incident_print`
  (1); console `print.test.tsx`, `announce.test.tsx`.
- Not done: the optional `incident.printed` audit (the printable page has no server call of its
  own); attaching similar incidents as children waits for S2 on main.
