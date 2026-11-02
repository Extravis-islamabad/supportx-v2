### 2026-10-28 — WP-039 session 3: lock-out, MFA, my account, idle warning (lane B)

- Built on `feat/wp-039-session3`: see the WP-039 checklist; decision D-104 (pending review).
- Also merged today: #82 `subject_for` (lane C's workers decide like the API), #85 and #86 (the
  timing-test rule: 10x the target in PRs, the target in the nightly perf.yml), #87 kept drafts.
- Tests: identity, auth and access DB 97; console 217, ui 81, portal 7, forms 12. e2e under the
  QA lock (handed over by lane A), on a throwaway database: the full suite 55/55, including
  `sign-in-security.spec.ts` (4). Two e2e fixes: in `incidents.spec.ts` a Select option is
  clicked only after its list has finished opening (the MFA reminder exposed a race with the
  virtual list); in `sign-in-security.spec.ts` one card waits for the previous card's save.
- Outside scope, recorded: the record page's in-place edits and the composer keep no draft yet
  (lane A, WP-020d/e); REQ-SEC-030 (active sessions list) and REQ-SEC-027 (step-up) are V1.
