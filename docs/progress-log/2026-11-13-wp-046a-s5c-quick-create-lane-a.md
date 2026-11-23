### 2026-11-13 — WP-046a S5c part 1: quick create (lane A)

S5c as approved: copy N times, quick create, then server drafts. Quick create needs no
migration, so it goes first as its own PR. Copy waits for its migration number (`copy_limit`).
Drafts wait for WP-057 S3's field encryption (coordinator's answer 2).

## Done

- `apps/console/src/pages/incidents/QuickCreateDialog.tsx`: subject, requester and an optional
  priority. A manual priority asks for its reason, as the server does.
- The default template's starting values are sent with the create, and the server applies the
  template's rules. A 422 on a field the dialog lacks names it, with "Open the full form",
  which carries over the template and requester (REQ-INC-018 AC2).
- One Idempotency-Key per dialog, renewed after a field error.
- Incidents list: a Quick create button beside New. The list refetches and updates live
  (AC1).
- Labels in en, ar and ur.

## Tests

- `quickCreate.test.tsx` (2):
  - AC1: the body carries the template and its starting values, plus the key; the list loads
    again.
  - AC2: the needed field is named, and the full form opens with the template and requester.
- Incident console tests: 168 passed. Labels: 66 passed. Backend label checks: 22 passed.

## Still open

- Copy N times (REQ-INC-033), once its migration number is given.
- Server drafts (REQ-INC-019), once WP-057 S3 lands.
