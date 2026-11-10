### 2026-11-10 — Lane A polish: #318 review notes, read-only statuses, showcase records in Arabic and Urdu (lane A)

Branch chore/polish-lane-a-11.

**Done**

- **Incident statuses tab (lane C's coverage list, §17 item 3):** with a read-only licence nothing there saves. The resume switches and reason pickers are disabled, and Rename is a WriteButton.
- **Lane C's #318 notes:**
  - Portal settings show a refused save above the bar (FormProblem) instead of as a toast. A save that stopped after some owners took their part says so; the bar then counts only what is left.
  - Routing names a removed group or site as removed instead of '—' (en/ar/ur).
  - The closing tab's save bar sits below its card, as on every settings page.
- **Showcase seed:**
  - Three service requests in Arabic and Urdu, and two problems (one Arabic known error, one Urdu). Every tenant without them gets them, and existing records are never changed.
  - Three starter items featured on the portal's home, only while none is featured.

**Tests:** the statuses read-only test, the portal partial-save test, and the showcase journey counts (10 requests, 5 problems, 3 featured, 75 backdated) plus the problem re-run test.

**Open:**
- CatalogItemPage's raw DatePickers take lane C's `pickerFormat` once their QA10-P3-14 PR lands.
- The customFields flake was not reproduced (3×9 passes locally, no failed CI run found).
