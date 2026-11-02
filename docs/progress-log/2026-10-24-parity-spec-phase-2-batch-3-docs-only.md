### 2026-10-24 — Parity spec phase 2, batch 3 (docs only)

- Added `07-assets-cmdb-software-purchase-contracts.md` (183: 0 MVP / 145 V1 / 38 LATER),
  `08-knowledge.md` (93: 38 / 50 / 5) and `09-reports-dashboards.md` (116: 40 / 61 / 15).
- File 05 now cites the CMDB downtime and impact requirements (REQ-CMDB-020, REQ-CMDB-010).
- Spec gap found: architecture.md §6.1 puts products and vendors in `procurement` (Stage 3),
  but assets need them at Stage 2 (file 07 open question 2). §11.2 still says "Redis"
  (should be Valkey, D-004).
- No code changed. Next: batch 4 (10 AI, 11 admin and security, 12 integrations and ESM).
