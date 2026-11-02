### 2026-10-28 — WP-035: reports e2e in English and Arabic (lane C)
- QA lock from lane B/A; `reports.spec.ts` on the shared stack. Fixed: status tag contrast,
  exports and schedule runs failing visibly when the worker lacks a service, a stalled-export
  sweep. Reported to lane B: the consumers worker had no entitlement service (#91).
