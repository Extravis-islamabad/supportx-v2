### 2026-11-09 — Lane B polish: permissions from the coverage list, read-only controls, a test flake

- **Integrations defaults card** (coverage list §17 item 1): the screen asked for
  `integrations.manage`, which no role held, so the card never showed. It now asks for what the
  server saves the defaults with, `integrations.manage_email`. The test uses the admin's own grants.
- **Read-only licence** (lane C, §17 item 3): invitation resend and withdraw, and the role delete,
  are WriteButtons; the API-key rules' switches are disabled. One test each.
- **Realtime fan-out** (coordinator): the burst test no longer depends on wall time. It counts the
  windows the runner took and asserts one list message per window, every record once.
- **Parked for Haider:** which built-in role, if any, holds the portal department viewer
  permissions (`work_items.view_department`, `work_items.view_reports`).
- **Lane C:** removes the unused backend `ADMIN_PERMISSIONS` in their bundle (agreed).
