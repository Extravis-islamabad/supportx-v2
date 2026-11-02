### 2026-10-28 — Worker resilience: PostgreSQL and NATS restarts (lane B; must-fix before the pilot)
- **Cause:** at 14:37 the shared stack's relay and fan-out died when PostgreSQL and NATS
  restarted, and nothing brought them back.
  - The relay counted only connection errors as outages; "the database system is shutting
    down" (`CannotConnectNowError`) crashed it.
  - Monitoring calls ended the process on a NATS error.
  - Consumers charged database outages to events as attempts, so a long outage dead-lettered
    them.
  - Readiness said "started", not "connected".
- **Fix:** see events.md, "When PostgreSQL or NATS restarts".
  - Settings: `SUPPORTX_WORKER_GIVE_UP_SECONDS` (300) and
    `SUPPORTX_EVENT_BACKLOG_STALLED_SECONDS` (120).
  - `/ready` gains `event_delivery: ok|stalled` and the reasons `disconnected` and `backlog`.
  - Administrators see a banner.
- **Tests:**
  - `tests/resilience/test_worker_restarts.py` restarts real containers: every event is
    published and claimed once, nothing is dead-lettered, the relay is unready during the outage
    and both workers survive; a worker exits 1 past its give-up time. CI job "worker
    resilience".
  - The same test against main fails: ready while PostgreSQL was down; never exits.
  - Plus 14 unit tests, probe tests and a `/ready` test.
- Also: `GET /notifications/status` reads the app's settings, never a fresh `backend/.env`
  (found by lane A).
