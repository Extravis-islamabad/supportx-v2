### 2026-11-23 — WP-047a S1: raising a service request (lane A)

REQ-SR-014 (partly), REQ-SR-015 and REQ-SR-016, migration 0193 on 0184. The WP-047a plan was
approved by the coordinator the same day, with five conditions; lane C blocks the PR (feature
permissions).

## Done

- **0193:** `catalog_items.max_quantity` and `asks_needed_by`; `work_items.quantity`,
  `needed_by` and `expected_delivery_at`, with range checks. The "needed earlier" flag is read
  from the two dates, never stored.
- **Quantity (Professional):** item settings and the create path refuse it without `catalog`
  (403 `entitlement_required`, in the service, rule 5f); above the item's maximum it is the same
  field error in the form and the API. The estimate waits for the item price (REQ-CAT-020).
- **Expected delivery:** a new `sla.delivery_at` counts the item's resolution target on the
  calendar the clock would use; shown on the item before submitting and on the record, worked
  out again when approval completes.
- **Request again:** `GET /portal/service-requests/{id}/request-again` (own requests only): the
  current item's form with the earlier answers, attachments never copied, removed questions
  dropped and counted, a retired item refused with the reason.
- **Portal answers:** filtered in the portal service to the requester's own questions, for every
  portal read (condition 2); events and the requester's mails carry no answers.
- **Subject template:** a request with no subject takes its item's template.
- **Bulk on requests:** the requests list gets row checkboxes and the selection bar (assign,
  take), on the engine's visibility-first runner (condition 1).
- Portal form, request page, item admin and the console record; labels en/ar/ur.

## Checks

- On a standalone throwaway Postgres and Valkey (removed after): `test_request_raising_api.py`
  8 passed (incl. condition 1, condition 2 with its control, the per-edition test of condition 3);
  the catalogue, request, portal, approval and QA6 suites, 56 passed.
- Vitest: the portal's new file 6, the console's requests and item-admin files 27, and the
  suites whose fakes gained the new fields.
- ruff, mypy, tsc, ESLint, Prettier, import contracts, event schemas and the route map clean.

## Open

- REQ-SR-014 AC1 (the estimate) with the item price; bulk close, resolve, cancel and delete on
  requests (S5); a route-level feature declaration and a Feature column in the route map (lane
  C's CI area, recorded in Known gaps).
- A staff or approver answer (S4) must be stored apart from the requester's answers, so the
  portal's filter and request again never meet one.
