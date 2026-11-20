### 2026-11-20 — WP-046b S3b: the incident board, cards and calendar (lane A)

REQ-INC-111 and REQ-INC-112, migration 0182. Plan: approved by the coordinator (Q1 the
migration, Q2 12 columns with a stable order) and lane C (six conditions plus the calendar's).

## Done

- **0182:** `work_item_list_settings.layout` (table, cards, board, calendar) and `group_by`
  (status, priority, technician, group), both nullable with checks; expand only.
- **Lists:** list settings carry both; a save keeps every choice (the console and the 409 retry
  used to drop the row colouring; fixed). `POST /{type}/board` answers each column's count by
  the list's own body (scope, field access, the sealed rewrite, view, tag), in a stable order.
- **Console:** a labelled switch in the toolbar row (template B); cards (two densities, the
  unread cue, the colour mark, only the reader's list fields); the board on the shared
  StageBoard (status moves through the record's own lifecycle action and its dialogs, assign
  preset to the column, priority with its reason; "More columns"; "Show more"); the calendar
  (IncidentCalendar on calendarMath: month and week, "N more", roving arrows mirrored in RTL,
  Home/End, PageUp/PageDown, Escape back to its button).
- **StageBoard** (lane C's, rule 8, agreed): four optional props: the server's count ("25 of
  120"), `whyNot` (an enabled item with the reason in its name: rc-menu sets aria-disabled from
  `disabled` itself, and a disabled item is skipped by the arrows), a column footer, and focus
  back to the moved card's "Move to", or its column's heading when the card leaves.

## Checks

tsc, ESLint and Prettier clean; console 1,088 of 1,090 in a full run (the two others, problems
and dashboards, pass alone: load timing); ui board 7; backend board and list settings 32,
top-level 744; route map regenerated; events and import contracts clean.

## Open

- The Visual matrix states lane C asked for (board by status with a refused move, by
  technician with "More columns" open, cards in both densities, calendar month, week and "N
  more" open; en/ar, 390/1280, light/dark): next, with lane C's tooling.
- The shared calendar grid for ScheduleCalendar and IncidentCalendar: lane A's polish list.
