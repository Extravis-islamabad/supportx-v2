### 2026-11-11 — Lane A polish: QA-2026-11-11 re-check leftovers and minors

From the Chrome re-check of #401 on main 2d848b42 (coordinator's lock; shots in
~/Desktop/supportx-daily/2026-11-11-qa/, suffix -2d848b42), and the day's minors:

- F-03 leftovers: a staged record's stage shows by its name in the history, never its code. A
  send-back for re-approval reads as one sentence naming the changed fields ("… sent it back for
  approval again because Risk changed"), not "Sent back … because of to risk".
- V-06 leftover: My profile is centred like the other form pages. An antd Space is inline-flex,
  so FORM_COLUMN's auto margins need `display: flex`.
- Portal not-found: unknown portal addresses show "Page not found" with a way home, never
  "This area is being built". The dead coming-soon page is removed.
- F-10: the CAB pack's "Prepared …" and the zone note are on two lines. Lane C takes the zone's
  readable name in the shared ZoneNote.
- F-11: the changes list's Status column fits "Awaiting acceptance" (230 px).
- F-19: the freeze and maintenance windows table has a written empty state (en/ar/ur).
- V-07: the notification rules' "Only for priority" column has its own width, and its heading
  stays on one line.
- V-18: the routing rules table's scroll box is a named region a keyboard can reach
  (TableRegion).

Left for later (recorded in the polish queue): F-09 (the primary move and the header chip's
wording), V-09 (incident header actions), V-11 (the admin tab row waits for lane C's Tabs in #402;
the mixed Add button styles; Canceled/Cancelled is a house-style question for the product owner),
V-16 (catalog descriptions cut mid-word; the requests list's Approval column), and V-01 adoption
once #402 lands.
