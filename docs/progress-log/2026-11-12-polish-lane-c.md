### 2026-11-12 — Polish, lane C (QA-2026-11-11 minors and #402 review notes)

Branch fix/polish-c-2026-11-12. This is the weekly polish bundle; the DrillDrawer item joins when lane A's #396 lands.

**Done**

- **F-10:** the shared time-zone note names the zone in the reader's language ("Pakistan Standard Time", its Arabic and Urdu) with the exact code as its title, not the IANA code. The Arabic sentence now reads "الأوقات حسب …", so the zone's own "توقيت" isn't repeated.
- **Lane A's #402 notes:**
  - footer bars mount and unmount in any order: the tallest counts, and the page's value comes back only after the last bar;
  - the calendar test's matchMedia stub is always cleared.
- **Lane B's #402 note:** a new e2e, `form-footer.spec.ts`, checks a field reached by the keyboard sits clear of the footer bar at 390 and 1280. The full-page shots can no longer show that.

**Checks**

- ui dates and layout Vitest, the labels package, the change calendar Vitest, tsc and ESLint.
- The e2e runs in CI.
