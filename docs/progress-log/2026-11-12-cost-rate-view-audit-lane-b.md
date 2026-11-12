# 2026-11-12: cost rates, every view audited (D-164), lane B

- **What:** Haider decided (D-164, written by lane A with the cost rates part from lane B) that
  every view of a person's cost rate is audited, not only changes. `GET /users/{id}/cost-rates`,
  which is what the person card loads and refetches live, now writes one `user.cost_rate_viewed`
  entry per read. It names the rates shown and the current one, never an amount. The worklog cost
  snapshot through the `cost_rate` port reads no route and is not a view, so it writes nothing.
- **Rights:** unchanged and now confirmed. Only the tenant admin holds `users.view_cost_rates` and
  `users.manage_cost_rates` by default; both can be granted to a custom role.
- **Labels:** en, ar and ur for the new audit action.
- **Also:** a flaky check in `test_every_change_is_audited_with_old_new_and_the_date` looked for
  a bare "40" in the history values, which hold UUIDs. It now looks for the amounts.
- **Tests:** test_user_cost_rates_api.py 11/11, three runs in a row; tests/test_*.py 529 passed.
