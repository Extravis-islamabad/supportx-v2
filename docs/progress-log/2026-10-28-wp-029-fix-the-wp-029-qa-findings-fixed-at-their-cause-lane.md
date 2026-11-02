### 2026-10-28 — WP-029-FIX: the WP-029 QA findings, fixed at their cause (lane A)

- Every finding of ~/Desktop/qa-wp029/QA-REPORT.md fixed with a test named after its ID (see
  WP-029-FIX above), plus the availability follow-up; systemic rules in D-105: refusals at the
  form and never as error toasts, error labels always get their params (two CI checks), every
  counted label has its plural forms (CI check), one shared conflict dialog naming who, when and
  what in every editor, availability set by leads and admins with history, refused moves name
  who may run them.
- Small additive edits in lane B and C modules (409 details via `stale_version`; identity's
  `role_names` and people-name resolver); both lanes told.
- The shared dev stack now runs from `../supportx-v2-stack` (detached origin/main), never from a
  lane's working branch (LANES.md), after the stack picked up this branch mid-QA.
- C4: the 12 leftover QA custom fields of 2026-10-27 in Demo Company (11 "QA …" fields and
  "!!!") retired through the API under the QA lock (reversible; nothing deleted).
- `make check`: lint, typecheck, import contracts green; backend 1552 passed after fixing three
  tests (two expected the old 409 params; the files settings test read a developer's
  backend/.env, now `Settings.load(env_file=None)`); frontend all suites green.
- Noted by lane B's WP-039 QA: Urdu is about 380 label keys short (e.g. the portal header);
  Urdu becomes mandatory from Stage 2 (D-006), recorded here as a Stage 2 item.
