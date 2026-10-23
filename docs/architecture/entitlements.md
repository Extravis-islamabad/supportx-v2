# Entitlements: features, limits and licence state

What a customer may use (architecture.md §13; WP-009; ADR-021). One interface answers every
entitlement question, so SaaS and on-prem behave the same way and no code ever asks "am I running
as SaaS?" (CLAUDE.md rule f).

## In one paragraph

Every tenant has an **entitlement**: an edition (Essentials, Professional, Enterprise), the
features that edition includes plus any add-ons, counted limits (technicians, assets, department
desks, MSP customers, AI agent runs per month) and a term (start, expiry, maintenance end, grace
days). Where it comes from depends on configuration: a subscription row in SaaS, a licence file
on-prem. Everything else in the product only asks the licensing module: *is this feature
included? is there room for one more technician? may this tenant make changes right now?*

## Editions and features

The catalogue lives in one file: `backend/app/modules/licensing/domain/catalogue.py`. Each edition
includes everything in the one below it (product-plan.md §9).

| Edition | Adds these features | Default limits (technicians / assets / department desks / MSP customers / AI runs per month) |
|---|---|---|
| Essentials | incident, service_request, knowledge, sla, ai_assist | 10 / 1,000 / 1 / 0 / 500 |
| Professional | problem, change, release, catalog, cmdb, assets, discovery, procurement, workflows, ai_agents, monetx_integration | 50 / 10,000 / 1 / 0 / 5,000 |
| Enterprise | projects, esm, msp, advanced_reporting, sandbox, config_as_code, custom_functions, local_ai_runtime, compliance_packs | 250 / 50,000 / unlimited / 25 / 50,000 |

The default limits are placeholders until there is commercial input; a subscription or licence
that names a limit always wins. Requesters (end users) are never counted. On screen, every code
appears through labels: `feature.change` → "Change Management", `edition.enterprise` →
"Enterprise", `limit.technicians` → "Technicians" (English and Arabic, CI-checked).

## Licence states

The state is never stored. It is worked out from the term each time it is needed, so a licence
moves from active to grace to read-only on time without any background job:

| State | When | What happens |
|---|---|---|
| **active** | inside the term | everything the plan includes works |
| **grace** | expired (or, from WP-013, the licence stopped matching the machine) for at most `grace_days` (default 14) | everything still works; admins see a warning |
| **read_only** | after the grace period, or the subscription is suspended | people can view and export everything; every change is refused. Nothing is deleted or hidden. |
| **invalid** | no subscription or licence at all, or not valid yet | no features, no changes |

## How a module declares its feature

One line in the module's `ModuleSpec` (`backend/app/modules/<module>/__init__.py`):

```python
module = ModuleSpec(name="changes", routers=[router], feature="change")
```

That is all. The module registry wraps every route of the module with the entitlement guard
(`backend/app/core/entitlements.py`): a tenant whose plan lacks `change` gets 403 for every route
of the module, reads included. The feature key must exist in the catalogue or the app refuses to
start. Modules without `feature` (identity, organization, licensing, system) are available in every
edition.

Two decorators mark exceptions on single endpoints:

- `@read_only_exempt`: a POST that must keep working in read-only mode (exports, "download my
  data"). GET, HEAD and OPTIONS never need it.
- `@entitlement_exempt`: a route that runs before there is a tenant (health probes, the login flow).

Inside services, ask the interface directly (all in `app.modules.licensing`):

```python
await licensing.require_feature(tenant_id, Feature.AI_AGENTS)   # 403 entitlement_required
if await licensing.has_feature(tenant_id, "cmdb"): ...
state = await licensing.current_state(tenant_id)                 # active / grace / read_only / invalid
check = await licensing.check_limit(session, LimitKey.ASSETS)    # advisory: used, limit, allowed
left = await licensing.remaining(session, LimitKey.ASSETS)       # None = unlimited
```

## Counted limits (adding a technician, an asset, a desk)

The module that owns the records counts them; licensing never reads another module's tables. The
owner registers a counter in its `ModuleSpec`:

```python
module = ModuleSpec(..., usage_counters={"technicians": count_technicians})
```

Before adding one, in the **same transaction** that inserts it:

```python
await licensing.reserve_capacity(session, LimitKey.TECHNICIANS, code="technician_limit_reached")
```

`reserve_capacity` takes a PostgreSQL advisory lock for (tenant, limit), counts, and refuses with
403 when the limit would be exceeded. Concurrent additions queue on the lock, so two (or twenty)
people signing in at the same moment can never go over the limit: proven by a 20-way race test.
`hold_limit` takes the same lock earlier, when the caller must first look at its own data (e.g.
"is this user already a technician?").

Technicians are checked at just-in-time provisioning (`identity_access/service/users.py`): only a
**new** technician seat is checked (a new user, or a requester promoted to technician in
Keycloak). Existing technicians are never re-checked, so lowering the limit below current use
locks nobody out (§13.6); it only stops further additions.

## What users see when blocked

Every refusal is an RFC 9457 problem with a code the UI turns into a translated message:

| Code | When | English message |
|---|---|---|
| `entitlement_required` (params: `feature`) | the plan does not include the module | "Your plan does not include this feature." (plus the feature's label) |
| `read_only_mode` (params: `reason`) | any change while read-only or invalid | "Your organisation is in read-only mode. You can view and export data, but changes are paused until the licence is renewed." |
| `technician_limit_reached` (params: `limit`, `max`) | a new technician signs in or switches in, and all seats are taken | "All technician seats in your organisation’s plan are in use. Ask your administrator to free a seat or add more." |
| `limit_reached` (params: `limit`, `max`) | any other counted limit | "Your plan’s limit for this has been reached. Ask your administrator to extend the plan." |

A browser login that is refused lands back on the app with `?auth_error=technician_limit_reached`
and the same translated message (never raw JSON).

During the grace period, responses to tenant admins carry `SupportX-Licence-State: grace`,
`SupportX-Licence-Grace-Ends` and `SupportX-Licence-Days-Left`, and `GET /api/v1/entitlements`
returns `admin_warning: true`, so the console can show a banner ("Licence warning: renew before the
grace period ends to avoid read-only mode.").

## GET /api/v1/entitlements

For the UI to hide menus it cannot use and show notices. The server stays the real enforcement.

```json
{
  "edition": "professional", "state": "active", "state_reason": null, "writable": true,
  "grace_ends_at": null, "days_left": null, "admin_warning": false,
  "features": ["ai_agents", "ai_assist", "assets", "catalog", "change", "..."],
  "limits": [{"key": "technicians", "limit": 25, "used": 7, "remaining": 18}, "..."],
  "term": {"starts_at": "...", "expires_at": null, "maintenance_until": null, "grace_days": 14}
}
```

`used` is shown to technicians and admins only (requesters get `null`), and stays `null` for limits
no module counts yet (assets, departments, MSP customers, AI runs). No secrets: no signature,
customer name, licence ID, installation ID or fingerprint.

## Where the data comes from: providers

`SUPPORTX_ENTITLEMENT_PROVIDER` picks one (read only inside the licensing module):

| Value | Provider | Source |
|---|---|---|
| `subscription` (default) | `SubscriptionProvider` | `tenant_subscriptions`: one row per tenant (edition, add-on features, limit overrides, term, status). A platform table: the app reads only its own tenant's row and can never write it; plans are written by platform tooling as the migrator role (`make db-seed`, `make dev-subscription`, later the SaaS control plane, §13.8). No row = no entitlement. |
| `licence_file` | `LicenceFileProvider` | the licence JSON at `SUPPORTX_LICENCE_FILE` (§13.3 format), read and verified at startup; the same licence applies to every tenant of the installation. |

Tests use `StaticProvider` (fixed entitlements per tenant).

**Unsigned licences.** Until WP-013, nothing can verify a signature. An unsigned licence file is
accepted only in the `dev` and `test` profiles. In `production` it is rejected and **the API
refuses to start**, logging `licence_rejected reason=licence_unsigned` (§13.6: "signature invalid
→ service refuses to start"). A signed file is refused everywhere for now
(`signature_verification_unavailable`).

## Caching

Entitlements are cached per tenant in Valkey (`<prefix>ent:<tenant>`, TTL
`SUPPORTX_ENTITLEMENT_CACHE_TTL_SECONDS`, default 300 s). Every plan change writes
`licensing.entitlement.changed` to the outbox in the same transaction; the consumer
`licensing__invalidate_cache` bumps the tenant's cache generation, and every API process reads the
new plan on its next request (about a second end to end on the dev stack). A generation counter
stops a request that read the old plan just before the change from writing it back afterwards.
If Valkey is down, the provider is asked directly; Valkey never decides an entitlement. Rate-limit
budgets (WP-008) are multiplied by edition: Essentials ×1, Professional ×2, Enterprise ×4.

## Where WP-013 plugs in

WP-013 (Rust licence core, ADR-009) replaces two small objects and adds one task; nothing outside
the licensing module changes.

1. **Signature (Ed25519).** `backend/app/modules/licensing/__init__.py`, `build_provider()`: replace
   `DevLicenceVerifier(...)` with a verifier backed by licence-core. Contract
   (`service/ports.py`, `LicenceVerifier.verify(document)`): verify `document.signature` over
   `document.signed_payload` (canonical JSON of every field except `signature`, see
   `domain/licence.py`) with the public key compiled into the binary; raise
   `LicenceRejectedError(reason=...)` to refuse. Unsigned licences then stop being accepted
   anywhere except tests.
2. **Fingerprint and clock rollback.** Same place: replace `NoInstallationCheck()` with
   licence-core's check. Contract (`InstallationCheck.degraded_since(document, now)`): return
   `None` while 3 of 5 hardware components match and the clock has not gone back, otherwise the
   moment the check first failed. The domain then starts the grace period from that moment
   (`Entitlement.degraded_since`) and moves to read-only after `grace_days`, exactly like expiry.
3. **Re-check every 15 minutes (§13.5).** Add a periodic task (Temporal schedule once workers
   exist) that calls `LicenceFileProvider.reload()` and, if the result changed, records
   `licensing.entitlement.changed` (`source="licence"`).
4. **Licence import.** The activation flow (§13.2) writes the new file, then calls `reload()` and
   records the same event.

Search for `TODO(WP-013)` and `WP-013 hook` in `backend/app/modules/licensing/` to find each spot.

## Guards

- **No deployment-mode checks**: `app/modules/licensing/tests/test_deployment_mode_guard.py` parses
  every Python file in `app/` and `workers/` and fails on identifiers or strings like `saas`,
  `on_prem`, `air_gapped`, `deployment_mode`, or use of the provider settings, outside the
  licensing module.
- **Only licensing touches providers**: import-linter contract "Only the licensing module touches
  entitlement providers" (`backend/pyproject.toml`).
- **No self-granted plans**: the application role has SELECT only on `tenant_subscriptions`, and
  only for its own tenant (RLS guard + tests).

## Known gaps

- On-prem limits are counted per tenant. An installation with several tenants (MSP on-prem) would
  need installation-wide counting through a platform-level usage counter.
- Assets, department desks, MSP customers and AI agent runs have no counters yet; they arrive
  with their modules (`usage_counters`), and AI runs need a monthly meter.
- The UI does not read `/api/v1/entitlements` yet (menus, banners): WP-010/WP-015. Live refresh of
  open consoles on `licensing.entitlement.changed` comes with the realtime fan-out (WP-011).
- Admin targeting uses the `tenant_admin` realm role until the policy layer exists (WP-016).
- Deleted users do not exist yet; when they do, re-provisioning a soft-deleted technician must
  take a seat again.
