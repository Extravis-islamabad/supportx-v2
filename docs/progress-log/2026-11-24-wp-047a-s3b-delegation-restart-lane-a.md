### 2026-11-24 — WP-047a S3b: approval delegation and restart (lane A)

**Scope:** REQ-SR-035 and REQ-SR-041 on migration 0197, under the approved S3 plan and the
coordinator's conditions 1 and 3. The branch is cut from S3a's, and its PR opens once #604 merges.

**Built:**
- **Domain** (`domain/delegations.py`): the checks, overlaps, windows and restart keys.
- **Delegations service:** routing at every row creation (`approval_rows.prepare`, which also
  stamps the round), the end and expiry, the notices to both people, and the routes.
- **Restart:** the restart service, the answers edit, and the requested-for hook in the record
  update.
- **Catalog:** `restarts_approval` and `restart_on`.
- **The new right:** `requests.manage_delegations`.
- **Console:** the Delegations page, "on behalf of" and earlier rounds on the Approvals tab, and
  the catalog switches.
- **Labels:** en, ar and ur.

**Checks run:**
- module and domain tests;
- label tests: 106 passed;
- events, OpenAPI and the route map (light);
- console tsc and ESLint;
- touched Vitests: 39 passed.

The DB tests run in the heavy slot.
