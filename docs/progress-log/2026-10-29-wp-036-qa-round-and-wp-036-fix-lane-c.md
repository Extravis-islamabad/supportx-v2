### 2026-10-29 — WP-036 QA round and WP-036-FIX (lane C)

- QA (~/Desktop/qa-wp036/QA-REPORT.md): live updates for a second user in 0.37–0.47 s, scope,
  drill-down, free grid, Arabic and 390 px pass; 7 bugs and 2 cosmetic notes.
- Fixes, one failing test per ID first (~/Desktop/qa-wp036/FIX-REPORT.md):
  - a concurrent edit was silently lost: the edit now keeps its starting version, so the second
    save meets the conflict dialog;
  - sharing's "Keep my changes" did nothing;
  - keyboard moves could overlap widgets;
  - shipped widget names were stored in the adder's language;
  - Add widget labels and the widget scroll region were not accessible;
  - widgets now say which dashboard filters apply;
  - narrow doughnuts cut their labels, and widget titles were cut by the chart-type text.
- Conflict sweep across lane C's editable records: all send If-Match and open the shared dialog;
  missing console tests added.
- The 390 px header findings (BUG-06/07) move to the header fix.
