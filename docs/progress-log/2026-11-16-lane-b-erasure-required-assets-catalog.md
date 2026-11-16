### 2026-11-16 — Lane B: assets and service_catalog required before any erasure (ADR-052)

The erasure readiness check on main (a472369bc) found two modules holding person data with no
erasure port and not in `REQUIRED_PORTS`: assets (ownership, assignments, loans, bookings, label
jobs, audit auditors; lane B's per ADR-052 §4) and service_catalog (items' owner and default
technician; lane A). An erasure could have run and skipped them. This closes that window until
their ports land (the coordinator, 2026-11-14):

- `assets` and `service_catalog` are in `REQUIRED_PORTS`.
- Approval now refuses `erasure_port_missing` (params: the missing keys) while any required port
  is unregistered, as the job already did before its first step.
- Tests: `tests/erasure_pending.py` stands in no-op ports for the pending keys in DB tests
  (`tests/db/conftest.py`), never replacing a real one; the domain test expects exactly the
  pending keys missing; a DB test proves approval refuses while a required port is missing.
  Each real port's PR removes its key from `PENDING`.
