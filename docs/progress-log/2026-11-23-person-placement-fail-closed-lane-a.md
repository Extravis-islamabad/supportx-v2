### 2026-11-23 — person_placement fails closed (lane A)

A follow-up to lane B's review of #582 (WP-047a S2a), assigned by the coordinator; no migration.

`identity_access.person_placement` answered an ID with no visible row (a random ID, or another
tenant's user, which RLS hides) and `None` with `Placement(None, None)`, whose defaults are
`active=True, can_sign_in=True`. It now returns `NOBODY`: not active, no sign-in, no site,
department or manager.

## Callers on main (23), and what changes

- **Read `active` / `can_sign_in`; stricter now:**
  - `work_items/service/approval_stage.py` `open_stage`: an unknown named approver is
    inactive, so the stage goes to the backup or the administrators instead of failing on the
    approver's foreign key.
  - `work_items/service/approvals.py` `reroute_inactive`: an unknown approver is rerouted.
  - `work_items/service/problem_approvals.py`: an unknown person is not an approver.
  - `work_items/service/work_items.py` `_person_facts` (`may_raise_for_people`,
    `_on_behalf_problems`): an unknown target is never in scope. With `all_users` it used to
    pass the scope check and be refused only by a later field check (a 422); it is now the
    scope's 403 `on_behalf_out_of_scope`.
- **Read only site, department or manager (unchanged: those were already `None`):**
  - assets: acknowledgements, ownership (two), refs, ticket_access;
  - knowledge: articles;
  - work_items:
    - automation;
    - change_types (two);
    - escalations;
    - portal;
    - requester_names (two);
    - work_items.py's own-manager check and the requester's placement.

## Checks

- `tests/db/test_person_placement_fail_closed.py`: a random ID, tenant B's user and `None` read
  as nobody, while a real person reads as before; raising on behalf of a stranger under
  `all_users` gives 403, the ID never echoed, while a real colleague is allowed.
- Run once without the fix: both new tests fail (the unknown ID reads `(True, True)`; the
  on-behalf case gives the later 422), so they pin the change.
- The existing DB files of every caller area, on lane A's throwaway Postgres.
- App tests and the pre-push set.
