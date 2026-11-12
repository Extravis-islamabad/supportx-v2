### 2026-11-12 — User cost rates for worklog costs (lane B; for lane A's WP-046a S3, REQ-INC-068)

Branch feat/user-cost-rates. The design was approved by the coordinator; migration number 0148.

- **Table** `user_cost_rates` (identity_access, migration 0148, down revision 0142 for now): a
  person's rate per hour from `effective_from` on, Numeric(12, 2) ≥ 0, in the tenant's base
  currency when set (organization's `base_currency`). RLS forced, actor audit, no DELETE grant;
  a unique live start per person and an index (tenant, person, start DESC). The downgrade
  refuses per tenant while any rate exists, removed ones included (rule 5h).
- **Rights** `users.view_cost_rates`, `users.manage_cost_rates` (names pending Haider's
  naming): tenant admin only by default; technician, team lead and the other built-in roles do
  not hold them.
- **Service** `identity_access/service/cost_rates.py`: list (newest start first, with the
  state current, future or past), set, change (current or upcoming only, If-Match), remove
  (soft). Changes need both rights, as a change answers with the rates. A service identity is
  refused with `not_a_person`.
  History on the rate itself (amounts); the person's own field history gets a part entry with
  the rate's ID only (never the amount, as that history goes with the person record). Outbox
  event with IDs only; realtime on the `user_cost_rates` list channel.
- **Audit:** `user.cost_rate_changed` on the person, details: rate ID, change, currency, old and
  new rate, old and new start.
- **Port:** `cost_rate(session, user_id, at) -> Decimal | None` exported from
  `app.modules.identity_access`; aware `at` only; no permission check (snapshots).
- **Console:** the person drawer's "Cost per hour" tab, with the current rate, the rates with
  their state, and set, change and remove. The api-client hooks are `useCostRates` and
  `useCostRateActions`. Labels are in en/ar/ur.
- **Tests:** domain unit tests and a realtime route test. DB tests: RLS read and write, the
  port, rights (view without manage, people admin without the rights, technician), If-Match
  and 428, a superseded or taken start, a naive time (422), idempotent create, a service
  identity, no rate on the user GET, list or search, audit entries and refused attempts, IDs-only
  events, and the 0148 downgrade refusal. Vitest covers the card's visibility, a viewer
  without manage, set with Idempotency-Key, the If-Match change, a refusal in words, and the
  live refetch.
- **Left for later:** `work_items/service/cost_rate_port.py` once lane A's `CostRates` port is
  on main. There is no people admin guide to add a line to yet.
