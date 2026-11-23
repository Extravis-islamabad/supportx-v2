### 2026-11-11 — QA majors, lane C (bundled QA PR)

Branch fix/qa-c-2026-11-11. These are the 8 majors from the 2026-11-11 QA round assigned to lane C. Minors go to the weekly polish PR.

**Fixed**

- **V-03:** chart labels in dark mode. `withTokenColours` now themes pie and donut series too: label text, no text border, and label lines in the token colours.
- **F-07:** workflow steps are never shown by their raw IDs.
  - A step shows its type label, numbered only when a type repeats ("Timer 2"). The naming lives in `@supportx/flow` (`stepNames`) and is shared by the canvas, outline, test panel, record Workflows tab, the versions move dialog and the runs list.
  - The runs step filter picks from the chosen workflow's published steps.
- **F-05:** the note and tasks steps have their own forms instead of JSON only.
  - Note: text per language in the shared TranslatedField, plus the private switch.
  - Tasks: a checklist of titles per language, an owner group and due days.
  - Still on the Advanced editor (follow-up): approval, field update, set variable, split, join, sub-flow, function and webhook.
- **V-02:** the designer fits the whole workflow once its steps are measured, with a zoom ceiling of 1. Output names sit inside the step above their handles, not on the links leaving it.
- **V-05:** the shared ScheduleCalendar (changes and releases) below 768 px:
  - the month's seven columns share the width, and a day's number opens its day view;
  - the week is a list of days.
- **V-01:** form footer bars.
  - FormFooter and StickySaveBar keep their height clear as the window's scroll padding, so a field reached by Tab is never behind the bar (WCAG 2.4.11).
  - The visual matrix's full-page shots kept the window height for layout and drew the bar mid-form. They now draw it where it sits at the end of the page (`data-sticky-footer`).
- **F-06/V-04:** tabs that don't fit.
  - A shared `Tabs` in `@supportx/ui`: a row wider than its box scrolls by buttons on its two ends, outside `role=tablist` (axe stays clean), mirrored in RTL. A focused tab scrolls into view.
  - All 20 tab rows use it, and ESLint refuses antd's `Tabs` elsewhere.

**Checks**

- Vitest suites for labels, ui, flow, charts, console and portal.
- `make frontend-lint`.
- Matrix proof: change, asset and release records and the designer at 390 and 1440, en and ar, on the PR.
