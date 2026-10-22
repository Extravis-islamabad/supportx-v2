# Modules: the module contract

Each folder here is one module. Business modules come from architecture.md §6.1 (`work_items`,
`sla`, `cmdb`, ...); the only other one is `system` (process health, ADR-018), which is also the
worked example of this contract. New modules need an ADR (CLAUDE.md §4).

## Registering a module (no edit to main.py)

The app factory imports every package in `app/modules/` at startup and reads one object from its
`__init__.py`:

```python
# app/modules/<name>/__init__.py
from app.core.modules import ModuleSpec
from app.modules.<name>.api.routes import router

async def _startup(app: FastAPI) -> None:   # optional: build clients, warm caches
    app.state.<name>_service = ...

async def _shutdown(app: FastAPI) -> None:  # optional: close what startup opened
    ...

async def _on_ticket_created(event: Mapping[str, Any]) -> None:  # optional, wired in WP-007
    ...

module = ModuleSpec(
    name="<name>",                       # must equal the folder name
    routers=[router],                    # mounted under /api/v1 (give the router its own prefix)
    on_startup=[_startup],               # run in module-name order
    on_shutdown=[_shutdown],             # run in reverse order
    event_handlers={"work_items.created": [_on_ticket_created]},
)
```

Rules the registry enforces at startup (`app/core/modules.py`):

- every package under `app/modules/` must define `module = ModuleSpec(...)`;
- `ModuleSpec.name` must equal the package name, and names must be unique;
- startup hooks run in name order, shutdown hooks in reverse; event handlers from all modules are
  merged per event type into `app.state.event_handlers` for the event bus (WP-007).

See `system/__init__.py` for a complete, tested example (router + startup hook that builds the
readiness service from settings).

## Shape (architecture.md §6.3, §6.4)

```
app/modules/<module>/
  __init__.py     # PUBLIC: the ModuleSpec plus the service interface other modules may import
  events.py       # PUBLIC published event contracts (payload schemas, event type codes)
  api/            # FastAPI routers + request/response schemas. No business logic.
  service/        # use cases: own the transaction, permission + entitlement checks, outbox events
  domain/         # entities, value objects, state machines, policies, ports. Pure Python, no I/O.
  infra/          # repositories, adapters, outbox writer. Only layer touching DB or network.
  tests/
```

Dependencies point inward: `api → service → domain`, with `infra` implementing the ports (protocols
in `domain`) that `service` needs. The module's `__init__.py` is the composition root that wires
infra into services.

## Errors

Raise the classes in `app/core/errors.py` (`NotFound`, `Conflict`, `ValidationFailed`,
`PermissionDenied`, `EntitlementRequired`, ...). They become RFC 9457 problem details with a stable
`code` and a `message_key` (`errors.<code>`). Every code needs an English and Arabic label in
`frontend/packages/labels` (enforced by `backend/tests/test_error_labels.py`). Never put internal
detail in an error; it is logged server-side only.

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
