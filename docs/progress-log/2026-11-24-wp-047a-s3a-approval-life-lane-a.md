### 2026-11-24 — WP-047a S3a: approval reminders, escalation and clarification (lane A)

**Scope:** REQ-SR-034, REQ-SR-036 AC2 and REQ-SR-037 on migration 0196, following the S3 plan
the coordinator approved today (split into S3a and S3b, Q1 to Q5 as proposed).

**Built:**
- **Domain:** a pure reminder plan (`domain/approval_reminders.py`), the clarification codes,
  and `escalate_to` on the catalog stage and the request's snapshot.
- **Sweep:** `request_approval_reminders`, a claim-once sweep in the existing pattern, capped
  per run.
- **Escalation:** next to the primary, counted as one family vote (`close_family`,
  `family_states`).
- **Clarification:** the route, `conversations.add_system_entry` and the answer consumer.
- **Portal:** the request's conversation and reply routes.
- **Settings:** the tenant's schedule.
- **Screens and labels:** console, catalog, settings and portal, in en/ar/ur.

**Checks run:**
- **DB tests on lane A's throwaway Postgres and Valkey** (removed afterwards):
  - the new API file: 9 passed;
  - the 0196 migration test and models_match: 14 passed;
  - ten touched approval, catalog, portal and request files: 79 passed.
- **Other checks:**
  - module domain tests: 331;
  - `tests/test_*.py`: 790;
  - lint-imports: 22 kept;
  - events-check: no breaking change;
  - OpenAPI diff against main: no breaking change;
  - the route map;
  - console and portal tsc and ESLint;
  - touched Vitests: 41 console, 11 portal.

**Found on the way:**
- The portal had no conversation on requests, which 037 AC1 needs. It is added here.
- `stage_snapshot.without_person` now uses `dataclasses.replace`, so a new stage field can never
  be dropped silently.

**Next:** S3b (0197): delegation and the restart after a relevant change.
