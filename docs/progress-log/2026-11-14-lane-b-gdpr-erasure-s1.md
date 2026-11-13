### 2026-11-14 — Lane B: GDPR person erasure S1 (D-171, ADR-052)

- **Scope:** ADR-052 S1, the server side only (no screens): legal hold, the two-admin request
  flow, the erasure job and lane B's ports. Migration 0161 (down revision 0159).
- **Built:**
  - Migration 0161: `person_erasures` (tenant RLS, partial unique index on open erasures, state,
    reason and step checks, four-eyes check, `port_module`/`port_cursor` for batches), users'
    `legal_hold_*` and `erased_*` columns, DELETE on `user_cost_rates` and `list_settings`.
    The downgrade refuses while any tenant has an erasure, a hold or an erased person.
  - Rights `people.erase`, `people.export`, `audit.manage_holds` (tenant admin only).
  - `PUT /people/{id}/legal-hold`, `POST /people/{id}/legal-hold/lift` (RecentAuth, If-Match,
    audited with the reason); `legal_hold.person_held` fails closed.
  - `POST /people/{id}/erasure` (RecentAuth, Idempotency-Key), `POST /erasures/{id}/approve`
    (RecentAuth, If-Match), `POST /erasures/{id}/reject`, `GET /erasures`, `GET /erasures/{id}`;
    realtime list `person_erasures`.
  - **Approval is always refused** with `erasure_report_unavailable` until the mentions report
    (S1b) fills `report`; the job also refuses an erasure without a report.
  - The job: steps 0-7, each its own transaction, step 4 one port batch per transaction
    (`ERASE_BATCH` 500), retries with backoff, refusals fail for good, everything audited; run
    by the schedule `identity_access__person_erasures` (30 s), which also expires requests.
  - Ports: action_links (110), organization (120), identity_access (510), list_settings (520),
    audit (530), files (590). `files.forget_uploader` deletes the person's uploads except kept
    ones; each kept file is audited with its reason.
  - `app.shared.erasure.ERASED_ON_REQUEST`, the one D2a marker, with its label.
- **Changes to the plan:** the job runs from a schedule rather than an event consumer (it needs
  a database per step and picks up runs a crashed worker left). Keycloak sessions end through
  ADR-051's event per session. organization's and audit's ports are registered from
  identity_access (they cannot import it without a cycle).
- **Not done:** the person's own profile history is not blanked (needs a definer function
  through a code-owned helper; see PROGRESS.md). Security-notice marks: none exist on main.
