### 2026-11-24 — WP-057 S4c follow-up: a grant's "Hide people's names too" tick (D-180, lane C)

Migration 0188, which the coordinator reserved on 2026-11-20. Lane B blocks the identity parts.
Lane A gave its rule 8 OK for the incident screens; `pages/requests/Approvals.tsx` is left to lane
A's S2b. This completes WP-057 S4c.

## Done

- **0188:** `support_grants.mask_names`, false by default, so existing grants keep names visible
  (D-180's default). The downgrade refuses per tenant, with `app.tenant_id` set, while any grant
  has it on, because dropping it would show the hidden names.
- **The flag's path:** the API (in and out) and the domain request; the service's view and create
  path; the cached grant facts, with a fail-closed `judged_names_masked`; the request context
  (`auth.py`); the policy's support subject; and the BFF's `/auth/me` banner. Two column-list
  selects (the policy's and the BFF's) now name the column too. The create audit records
  `mask_names`.
- **Console:**
  - the grant form gains the tick (off by default), and the grant's details show it;
  - the `unmask` labels are corrected for D-180: it now opens other personal details only, since
    names show by default and e-mail and phone never show (en, ar, ur);
  - the incident parts that read a name directly go through `useHiddenPersonLabel` and
    `shownName`: conversation, followers, approvals, the record's details and person, parts,
    assign, bulk and the pickers. Twin names never get an e-mail suffix for a masked session.
- **Guide:** `docs/guides/vendor-support.md` explains the tick and "Show other personal details".

## Tests

- **Migration:** three tenants. Names stay visible after the upgrade; a downgrade is allowed with
  no tick and refused with one in the middle tenant. Without the refusal, the test fails.
- **Policy, session and fail-closed:**
  - the policy's subject takes the grant's tick;
  - a masked session's `/auth/me` says `names_masked`, the record shows neither the name nor the
    address, a name search finds nobody, and a staff session (the control) shows the name;
  - `judged_names_masked` fails closed;
  - each of the three paths (context, subject, banner) has a mutation that makes a test fail.
- **Vitest:** followers and the conversation say "Person hidden" for a masked session, with an
  unmasked control (the masked case fails without the wiring). The grant form sends the tick, and
  leaves it false when it isn't ticked.
- **Area suites:** incidents, admin security, vendor support and maskedPeople: 280 tests in 53
  files pass. The support DB and unit suites: 44 pass.
