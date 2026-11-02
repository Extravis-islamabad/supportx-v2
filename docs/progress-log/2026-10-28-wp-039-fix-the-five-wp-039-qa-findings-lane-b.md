### 2026-10-28 — WP-039-FIX: the five WP-039 QA findings (lane B)
One test per finding, named after it (~/Desktop/qa-wp039/QA-REPORT.md):
- **BUG-03 (high):** at the idle limit the screen did not sign out. The server had already ended
  the session, logout answered 401, and the 401 was swallowed. `useLogout` now treats 401 as
  "already signed out" and clears the session (`api-client/src/qa-wp039.test.tsx`).
- **BUG-01:** after "Send again" the first link still worked. Keycloak cannot withdraw one link,
  so resending makes an unused invitation account afresh, and the earlier link names an account
  that no longer exists (`test_bug_01_sending_again_stops_the_earlier_link`). Not covered: an
  account that existed before the invitation (no password yet) keeps its earlier links until
  they expire; it is not ours to delete.
- **BUG-02:** a dead link showed the sign-in failure text. The theme's `error.ftl` now shows
  "This link no longer works…" (en/ar/ur), because a sign-in failure never renders on the
  error page.
- **BUG-04:** Urdu for all 100+ texts of Keycloak's pages that SupportX shows. The test pins the
  key list from Keycloak 26.8.1's templates and refuses English left in the Urdu file.
- **BUG-05:** the Arabic update-password title is now "تحديث كلمة المرور", not "Password
  updated".
- **Systemic lessons checked:** the WP-039 screens use the shared conflict dialog and show
  refusals at the form (#98); no counted labels were added.
