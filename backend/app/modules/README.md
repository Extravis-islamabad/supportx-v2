# Domain modules — the module contract

Each folder here is one business module from architecture.md §6.1 (`work_items`, `sla`, `cmdb`,
...). No modules exist yet. The first one arrives in WP-005 (`organization`). Every module follows
the same contract.

## Shape (architecture.md §6.3, §6.4)

```
app/modules/<module>/
  __init__.py     # PUBLIC service interface: the only thing other modules may import
  events.py       # PUBLIC published event contracts (payload schemas, event type codes)
  api/            # FastAPI routers + request/response schemas. No business logic.
  service/        # use cases: own the transaction, permission + entitlement checks, outbox events
  domain/         # entities, value objects, state machines, policies. Pure Python, no I/O.
  infra/          # repositories, adapters, outbox writer. Only layer touching DB or network.
  tests/
```

Dependencies point inward: `api → service → domain`, with `infra` implementing the ports that
`service` needs.

## Boundary rules (architecture.md §6.1, CLAUDE.md rule e)

1. Another module may import only `app.modules.<module>` (the package root) and
   `app.modules.<module>.events`. Everything else (`api`, `service`, `domain`, `infra`, any other
   submodule) is internal.
2. A module never queries another module's tables. Use its public service interface, or react to
   its events.
3. Every business table carries `tenant_id` with an RLS policy, and every state change writes an
   outbox event in the same transaction (CLAUDE.md rules a and b).
4. Features are gated only through the `licensing` module's entitlement interface (rule f).

Rule 1 is enforced by `lint-imports` (`make lint`). The custom contract lives in
`backend/tooling/import_contracts.py`, and the `[tool.importlinter]` section of `pyproject.toml`
also keeps `app.core`/`app.shared` from importing modules. If the contract fails, expose what you
need through the target module's `__init__.py` or `events.py`. Never add an `ignore_imports`
entry to get the build green.
