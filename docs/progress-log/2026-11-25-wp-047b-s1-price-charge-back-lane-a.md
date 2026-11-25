### 2026-11-25 — WP-047b S1: item prices, the estimate and charge-back (lane A)

- Plan sliced S1-S9 and approved by the coordinator; S1 built (migration 0205, on 0202 for now,
  re-pointed after #630's 0204).
- Built:
  - the shared DSL's numeric comparisons with shared vectors;
  - item prices, option prices and charge-to;
  - the request's estimate, its D-184 visibility and the portal's live estimate;
  - fulfilment's frozen charge;
  - the charge-back report fields;
  - item names for reports (server and console, lane C's conditions);
  - D-184.md.
- DB run: six files, 24/24 after one real fix (a saved question dropped its option prices).
- Surveys moved out of 047b to a lane A engine WP (work_items, no ADR) plus lane C's designer;
  INC-103 moved from WP-046b.
