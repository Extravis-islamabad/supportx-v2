### 2026-11-10 — Lane A polish: portal conflict dialog, picker date format, person picker names (lane A)

Branch chore/polish-lane-a-12.

**Done**

- **Portal settings (lane C's #322 note):** a save someone else beat (409) opens the ConflictDialog. Reload shows the latest of all four owners and drops my edits. Keep mine loads the latest and keeps every edit that still differs.
- **Catalogue item life tab (QA10-P3-14):** the publish and retire pickers follow the person's date format and 12/24-hour time, as the shared DateTimeField does.
- **UserPicker (QA10-P4-16, rule 5d):** a chosen person missing from the loaded page is fetched by id and shows "Loading…" until named, never the raw id. The release form's template and path-note parts are lane C's.

**Tests:**
- portalSettings.test: a 409 opens the dialog, and Reload refetches and clears the draft.
- userPicker.test: names the person, never the id; it fails without the fix.
- The suites of every page using the picker pass, file by file (load average 42 at the time).
