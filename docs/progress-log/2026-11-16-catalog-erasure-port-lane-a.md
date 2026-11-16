### 2026-11-16 — The service catalog's erasure port and the D-171 starter item (lane A)

Lane B's erasure readiness check found person data in `service_catalog` with no port; lane B
makes the port required, so no erasure runs until it exists (the coordinator put it ahead of
WP-046b S2).

- `service_catalog/service/person_data.py` (`service_catalog`, order 520, band 500): the items whose owner,
  default technician, approval (named approvers, backup approver) or plan (task owners) name the
  person. Owner and approvers pass to the successor; the technician and task owners are cleared,
  so the group takes them. One bounded batch per call; history (source system, reason
  `erased_on_request`) and `service_catalog.item.changed`. Count labels en/ar/ur.
- `domain/starter.py`: the D-171 item "Personal data request (export or erasure)" in People and
  HR, two internal tasks for an administrator; the starter catalog is now 15 items.
- Tests: `tests/db/test_catalog_erasure_port.py` (every place handed over or cleared, history,
  a second run counts zero, another tenant and other people untouched); the starter counts in
  `test_catalog_admin_api.py`.

`service_catalog` joins `REQUIRED_PORTS` in lane B's own change (their file).
