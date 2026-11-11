### 2026-11-11 — The SLA and the trash (lane A, Haider 2026-11-10; follows #353)

- **Rules:**
  - The clock keeps running while a record is in the trash.
  - A trashed record fires nothing and sits in no live SLA queue (#353).
- **On restore:**
  - `work_items.restored_at` holds the latest restore (migration 0128); the history keeps each one.
  - The restore's history line names each open target's standing ("Resolution overdue by 3 h").
  - Overdue targets breach at the restore, not at the next sweep.
  - The console warns with the same words.
- **SLA reports:** filter and group on `restored_at` ("Restored from trash").
- **Tests:** lane B's two #353 asks (a trashed record fires after its restore; a gone one stops once and stays still); the restore's state, history, breach and report field; the words in en; 0128 up/down/up.
