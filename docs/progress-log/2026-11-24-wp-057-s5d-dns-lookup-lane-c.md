### 2026-11-24 — WP-057 S5d follow-up: the DNS lookup for verified domains (lane C)

REQ-SEC-010 is now done. Haider approved dnspython (ISC) through the coordinator, as D-183. There
is no migration. Lane B blocks this PR (identity and egress).

## Done

- **The lookup (`identity_access/infra/dns_txt.py`):** dnspython's asyncio resolver on the
  installation's own configuration (resolv.conf). It never names a public resolver, and a test
  checks the source for the well-known public addresses.
  - **Bounds:** a 2 s timeout per query and a 5 s lifetime; at most 20 TXT records read; a record
    longer than 1024 bytes is skipped, never cut.
  - **Outcomes:** a name that doesn't exist, or has no TXT, is an empty answer. A timeout, a
    refusal or no answering server is `DnsUnreachable`. No resolver configured is
    `DnsCheckUnavailable`, which never counts towards a lapse.
- **Wiring:** the service's `resolver` port now defaults to this lookup. The two exceptions moved
  to the domain layer, because infra may not import the service (the layers contract).
  `conftest.py` has an autouse fixture so that no test ever asks real DNS.
- **Manual verify:** unchanged, single-tenant only, with a reason, audited. The "unavailable" label
  (en, ar, ur) now says the host has no DNS server configured, instead of "not available yet".

## Tests

- **`identity_access/tests/test_dns_txt.py` (8 tests)** runs against a local fake DNS server on
  127.0.0.1, UDP and TCP on one random port, never the internet.
  - **Cases:** split strings joined; NXDOMAIN and no-TXT empty; an oversized record skipped (and
    the answer, too big for UDP, retried over TCP); at most 20 answers; a refusal is unreachable;
    a silent server gives up within the lifetime; no resolver configured is unavailable; the
    system resolver is bounded and names no public server.
  - **Stability:** stable over six runs.
  - **Mutation checks:** with the size cap or the answer cap removed, or NXDOMAIN no longer mapped
    to empty, a test fails.
- **Other checks:** ruff, ruff format, mypy and import-linter (22 contracts kept) all pass, as
  does `tests/test_docs_entries.py`.

## Open

- **CLAUDE.md §3:** the "Approved addition (D-183)" line waits for Haider to confirm it in lane
  C's own session. Lane C doesn't edit CLAUDE.md on a relayed request.
