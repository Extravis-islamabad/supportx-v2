# Local development setup

This guide gets the SupportX v2 backing services (database, auth, messaging, storage and so on)
running on your machine with Docker Compose. It is for **local development only**. Real
environments (SaaS, private cloud, on-prem) are deployed with the Helm chart (WP-014).

Everything lives in `deploy/compose/` and is driven from the repository root with `make`.

## 1. Prerequisites

| What | Notes |
|---|---|
| Docker Desktop (Mac or Windows) or Docker Engine (Linux) | Docker Compose v2 (`docker compose`) is included. |
| **At least 8 GB of memory for Docker** | Docker Desktop → Settings → Resources → Memory. The core set needs about 1 GB and the full set about 3.5 GB, but other containers and Docker's own VM need room too. |
| About 6 GB free disk | For images (≈ 4 GB) and data volumes. |
| `make`, `bash`, `curl`, `openssl` | Already present on macOS and most Linux systems. |
| uv and pnpm | Only for the application code (see `README.md` and `make setup`), not for this stack. |

Apple Silicon (M1–M4) Macs are fully supported: every image used is multi-arch (amd64 + arm64).

## 2. First-time setup

```bash
make dev-init     # creates deploy/compose/.env with random passwords (never overwrites it)
make dev-up       # starts the core services and waits until all are healthy (~1 min first time)
make dev-check    # proves each service works; prints a PASS/FAIL table
```

The first `make dev-up` downloads the images, which can take several minutes on a slow link.

`deploy/compose/.env` holds every dev password. It is git-ignored, unique to your machine, and
readable only by you. Look there whenever you need a password (see the table below).

## 3. Daily use

| Command | What it does |
|---|---|
| `make dev-up` | Start the **core** services (enough for most backend and frontend work). |
| `make dev-up-full` | Start core **plus** Temporal, Temporal UI, OpenSearch, ClickHouse and ClamAV. The first start takes several minutes because ClamAV downloads its virus signatures. |
| `make dev-ps` | Show every service and whether it is healthy. |
| `make dev-logs` | Follow all logs. One service only: `make dev-logs s=keycloak`. |
| `make dev-check` | Check every running service end to end. Services from the full set that are not running are reported as SKIP. |
| `make dev-down` | Stop everything. **Your data is kept** and is there again on the next `make dev-up`. |

You can switch between core and full at any time: `make dev-up` after `make dev-up-full` leaves
the full services running. Use `make dev-down` to stop everything.

### Running the console and portal (WP-010)

```bash
make backend-dev                                     # API on 127.0.0.1:8000
make worker-relay & make worker-consumers            # events (plan changes, cache refresh)
make worker-fanout                                   # live screens (WP-011): events → Centrifugo
make worker-indexes                                  # custom field indexes on request (D-088)
cd frontend && pnpm --filter @supportx/console dev   # http://localhost:5173
cd frontend && pnpm --filter @supportx/portal dev    # http://localhost:5174
```

Sign in with the dev users from section 4. Things to try: the navigation and **Ctrl+K**;
**Appearance** (navigation: top bar / side bar / compact side bar, stored on the server; light /
dark / high contrast, right-to-left, language); the tenant switcher
(multi@demo.test belongs to both companies); **Admin › Users** (as admin@demo.test); **My
profile** in the user menu (open it in two browsers and save in both to see the conflict
dialog); `/dev/components` (development builds only: chart, every error message). Licence states
are driven with `make dev-subscription` (see "Plans and licence limits"). Playwright: `make e2e`
(frontend/e2e/README.md). How the frontend is built: docs/architecture/frontend.md.

## 4. Services, ports and logins

All ports are bound to `127.0.0.1` only, so nothing is reachable from your network. They are in
the 2xxxx range to avoid clashing with other projects; each one can be changed in
`deploy/compose/.env`.

| Service | Set | Local address | Dev login (password variable in `.env`) |
|---|---|---|---|
| PostgreSQL 16 + pgvector | core | `localhost:25432`, databases `supportx`, `keycloak`, `temporal`, `temporal_visibility` | App: `supportx_app` / `SUPPORTX_APP_PASSWORD`. Outbox relay: `supportx_relay` / `SUPPORTX_RELAY_PASSWORD`. Migrations: `supportx_migrator` / `SUPPORTX_MIGRATOR_PASSWORD`. Admin: `postgres` / `POSTGRES_SUPERUSER_PASSWORD` |
| PgBouncer (transaction mode) | core | `localhost:26432`, database `supportx` | `supportx_app` / `SUPPORTX_APP_PASSWORD` |
| Valkey | core | `localhost:26379` | password `VALKEY_PASSWORD` (no username) |
| NATS + JetStream | core | `nats://localhost:24222`, monitoring <http://localhost:28222> | none (dev) |
| Keycloak (dev mode) | core | <http://localhost:28080> (admin console), health <http://localhost:28090/health>; realm `supportx` imported from `deploy/helm/supportx/files/keycloak/dev/` | `admin` / `KEYCLOAK_ADMIN_PASSWORD`; test users below |
| Centrifugo | core | <http://localhost:28000> (admin UI at `/`), WebSocket `ws://localhost:28000/connection/websocket` | admin UI password `CENTRIFUGO_ADMIN_PASSWORD`; server API key `CENTRIFUGO_API_KEY` |
| MinIO (S3) | core | API <http://localhost:29000>, console <http://localhost:29001>, bucket `attachments` | `supportx` / `MINIO_ROOT_PASSWORD` |
| Mailpit (fake email) | core | web inbox <http://localhost:28025>, SMTP `localhost:21025` | none; SMTP accepts any login |
| Temporal | full | gRPC `localhost:27233`, namespace `default` | none (dev) |
| Temporal UI | full | <http://localhost:28233> | none (dev) |
| OpenSearch | full | <http://localhost:29200> | none: security plugin disabled for dev |
| ClickHouse | full | HTTP <http://localhost:28123>, native `localhost:29010`, database `supportx_analytics` | `supportx` / `CLICKHOUSE_PASSWORD` |
| ClamAV (clamd) | full | `localhost:23310` | none |

Quick connection examples:

```bash
source deploy/compose/.env
psql "postgresql://supportx_app:$SUPPORTX_APP_PASSWORD@localhost:26432/supportx"   # via PgBouncer
valkey-cli -p 26379 -a "$VALKEY_PASSWORD" ping                                     # or redis-cli
curl -u "supportx:$CLICKHOUSE_PASSWORD" 'http://localhost:28123/?query=SELECT%20version()'
```

### Database roles (why there are four)

- `supportx_app` is what the API and the consumer worker use. It is **not** a superuser, owns nothing and has
  **no `BYPASSRLS`**, so PostgreSQL row-level security always applies to it. This is what keeps one
  tenant's data invisible to another (CLAUDE.md rule a). `make dev-check` proves it.
- `supportx_migrator` owns the `supportx` database and schema; Alembic migrations run as this role.
  Tables it creates are automatically usable (read/write, no DDL) by `supportx_app`.
- `supportx_relay` is used only by the outbox relay (WP-007). It can read and mark the rows of
  `outbox_events` for every tenant and has **no access to any other table** (not even `users`).
  See [docs/architecture/events.md](architecture/events.md#database-roles).
- `postgres` is the bootstrap superuser, used only by the init script, `db-bootstrap` and
  `dev-check`.

The app connects through PgBouncer (transaction pooling). Migrations, the outbox relay, Keycloak
and Temporal connect to PostgreSQL directly.

**Upgrading an existing dev stack to WP-007:** run `make dev-init backend-env` (adds the relay
password and URL to your `.env` files without touching existing values), then `make db-migrate`.
`db-migrate` first runs `make db-bootstrap`, which creates any role your data volume does not
have yet (here `supportx_relay`); it never changes existing passwords or data.

### Database: migrations and demo data

```bash
make backend-env    # writes/updates backend/.env (adds missing settings, never overwrites)
make db-migrate     # create/upgrade tables (as supportx_migrator, directly to PostgreSQL)
make db-seed        # dev tenants + plans (idempotent, never deletes or changes existing data)
make db-guard       # check that every table is tenant-isolated (RLS)
make db-current     # which migration the database is at
make db-bootstrap   # create missing roles/grants (run automatically by db-migrate)
```

### Plans and licence limits (WP-009)

`make db-seed` also gives each dev tenant a subscription (only if it has none; it never changes an
existing plan):

| Tenant | Plan | Technician seats |
|---|---|---|
| Demo Company | Enterprise, no expiry | 250 (edition default) |
| Other Company | Professional, no expiry | **2** (low on purpose) |

Show or change a dev tenant's plan with `make dev-subscription` (runs as the migrator role, writes
the `licensing.entitlement.changed` event in the same transaction; with `make worker-relay` and
`make worker-consumers` running, the API picks the change up within about a second):

```bash
make dev-subscription TENANT=other                                  # show the plan
make dev-subscription TENANT=other ARGS="--technicians 1"           # 1 technician seat
make dev-subscription TENANT=demo  ARGS="--expires 2026-10-19"      # expired: grace period
make dev-subscription TENANT=other ARGS="--expires 2026-09-01"      # past grace: read-only
make dev-subscription TENANT=other ARGS="--status suspended"        # suspended: read-only
make dev-subscription TENANT=other ARGS="--edition essentials"      # fewer features
make dev-subscription TENANT=other ARGS="--expires never --status active --technicians 2"  # reset
```

Other options: `--assets`, `--departments`, `--msp-customers`, `--ai-agent-runs-per-month` (a
number or `unlimited`) and `--grace-days`. `TENANT` is `demo`, `other` or a tenant UUID. The tool
refuses to run in the production profile.

Trying the technician limit by hand (Other Company: other@other.test already holds one seat):

1. `make dev-subscription TENANT=other ARGS="--technicians 1"`.
2. Sign in to the console as multi@demo.test (lands in Demo Company) and switch to Other Company:
   refused with "All technician seats in your organisation’s plan are in use. Ask your
   administrator to free a seat or add more." (`technician_limit_reached`). A direct login that
   is refused lands on the console with the same message.
3. Sign in as other@other.test: still works (existing technicians are never locked out).
4. `make dev-subscription TENANT=other ARGS="--technicians 2"`, switch again: allowed.
5. Lower it back to 1: both technicians keep working; only a third new one would be refused.

`GET /api/v1/entitlements` (signed in) shows edition, features, limits with usage, state and term.
Licence files instead of plans: `SUPPORTX_ENTITLEMENT_PROVIDER=licence_file` and
`SUPPORTX_LICENCE_FILE=/path/licence.json` (an unsigned file is accepted in dev/test only); see
docs/architecture/entitlements.md.

### Roles and permissions (WP-016)

SupportX, not Keycloak, decides what users may do (D-029). At each user's first login after
WP-016 their Keycloak roles are mapped once: admin@demo.test → Tenant administrator,
tech@demo.test / multi@demo.test / other@other.test → Technician, user@demo.test → Requester.
After that, change access in **Admin › Roles** and **Admin › Users** (click a user). With
`make worker-fanout` running, the user's open browser updates by itself within about a second
(menus, pages); without it, on their next request. How it works:
docs/architecture/authorization.md.

### Live updates (WP-011)

Every screen updates by itself when data changes (`make worker-fanout` must run; Centrifugo is
part of `make dev-up`; the Vite dev servers proxy `/connection` to it). Try two browsers side by
side: Admin › Users in one, sign in as another user in the other; My profile in both (presence
avatars, and a notice when the other one saves); `make dev-subscription` while a page is open
(the banner appears without a reload). How it works and how to make a new screen live:
docs/architecture/realtime.md.

### Events: watching them flow (WP-007)

Four terminals (the API, the relay, the consumers, a live view):

```bash
make backend-dev        # 1: the API (writes events to the outbox)
make worker-relay       # 2: outbox -> NATS JetStream
make worker-consumers   # 3: runs module consumers; in dev it logs every event it receives
make events-tail        # 4: prints every event as it arrives (Ctrl+C to stop)
```

Sign in and out of the console (<http://localhost:5173>) and you see
`identity_access.user.logged_in` / `identity_access.user.logged_out` appear within a second in
terminals 3 and 4. Other commands: `make events-tail since=10m`, `make events-tail
type=identity_access.>`, `make events-stats`, `make dlq-list`, `make dlq-replay seq=<n>`. Full
guide: [docs/architecture/events.md](architecture/events.md).

The dev tenants always have the same IDs; they match the Keycloak organizations' `tenant_id`
attribute:

| Tenant | Slug | ID |
|---|---|---|
| Demo Company | `demo` | `01900000-0000-7000-8000-00000000de30` |
| Other Company | `other` | `01900000-0000-7000-8000-00000000a7e2` |

### Signing in (WP-006)

```bash
make dev-up backend-env db-migrate db-seed   # once
make backend-dev                              # API on 127.0.0.1:8000
cd frontend && pnpm --filter @supportx/console dev   # console on http://localhost:5173
cd frontend && pnpm --filter @supportx/portal dev    # portal on http://localhost:5174
```

Open the console or portal: you are sent to Keycloak (realm `supportx`). Enter the email, then the
password (two steps). These **test users** are imported with the realm (dev only):

| Email | Password | Organization | Role | Locale |
|---|---|---|---|---|
| `admin@demo.test` | `Admin-Demo-2026!` | Demo Company | tenant admin + technician | en |
| `tech@demo.test` | `Tech-Demo-2026!` | Demo Company | technician | en |
| `user@demo.test` | `User-Demo-2026!` | Demo Company | requester | **ar** (UI opens right-to-left) |
| `other@other.test` | `Other-Corp-2026!` | Other Company | technician | en |
| `multi@demo.test` | `Multi-Org-2026!` | Demo Company **and** Other Company | technician | en |
| `nobody@nowhere.test` | `No-Org-User-2026!` | none (shows the "no organisation" message) | requester | en |

Keycloak admin console: <http://localhost:28080> (`admin` / `KEYCLOAK_ADMIN_PASSWORD`). Five wrong
passwords lock a user for a while (brute-force protection is on even in dev). The realm is imported
only when it does not exist yet: after changing `deploy/helm/supportx/files/keycloak/dev/supportx-realm.json`,
delete the `supportx` realm in the admin console (or `make dev-reset`) and restart Keycloak.

The API's tenant comes from the login session. For scripts and quick `curl` tests you can still let
the API trust an `X-Tenant-ID` header, but only by opting in: add `SUPPORTX_DEV_TENANT_HEADER=true`
to `backend/.env` (dev profile only; production always ignores the header). How it all works:
`docs/architecture/authentication.md` and `docs/architecture/tenancy.md`.

`make db-downgrade` rolls back one migration and asks you to type `yes` first, because it can drop
tables and their data. Backend tests never touch the `supportx` database: they create throwaway
`supportx_test_*` databases and drop them afterwards.

## 5. Resetting safely

`make dev-down` never deletes data. To wipe **all** local dev data and start fresh:

```bash
make dev-reset
```

It lists the exact volumes it will delete (only `supportx_dev_*` volumes owned by this stack) and
does nothing unless you type `yes`. Your `.env` file is kept. Then run `make dev-up` again.

When you need a reset:

- You changed a password in `.env`. Passwords are written into the databases on first start only,
  so services fail to log in until the volumes are recreated.
- You changed `deploy/compose/postgres/initdb/` (the script runs only on an empty database).
- A volume is corrupted or you simply want a clean slate.

To create a brand-new `.env` too, delete `deploy/compose/.env` **after** `make dev-reset`, then run
`make dev-init`.

## 6. Troubleshooting

**"port is already allocated" / "address already in use"**
Another program or container is using that port. Find it with `lsof -nP -iTCP:<port> -sTCP:LISTEN`
(or `docker ps`), then either stop it or change the port in `deploy/compose/.env` (for example
`POSTGRES_PORT=25433`) and run `make dev-up` again. Only the host side of the port changes; the
services still talk to each other on their normal ports.

**A service keeps restarting, or exits with code 137 (out of memory)**
Docker has run out of memory. Check `docker stats`. Give Docker Desktop more memory (Settings →
Resources, 8 GB or more), stop other projects' containers, or use `make dev-up` (core) instead of
`make dev-up-full`. OpenSearch, ClamAV, Keycloak and ClickHouse are the heaviest services and each
has a memory limit in `docker-compose.yml`.

**`make dev-up` says "container ... is unhealthy" or times out**
Run `make dev-logs s=<service>` to see why. Keycloak and OpenSearch can take a minute on a cold
start. ClamAV's first start downloads signatures (~300 MB) and can take several minutes;
`make dev-up-full` waits up to 15 minutes.

**PDF report exports fail with "PDF export is not available on this server"**
PDFs are made by WeasyPrint, which is only in the worker image (D-100 D8), so `make
worker-consumers` cannot make them. Install Pango once (`brew install pango`), stop the consumers
and run `make worker-consumers-pdf` instead: the same worker, with the `pdf` dependency group and
the library path WeasyPrint needs. CSV and XLSX work with either. `make backend-test-pdf` runs
the PDF tests the same way.

**Apple Silicon: "no matching manifest for linux/arm64"**
All images in `docker-compose.yml` support arm64. If you add or upgrade one, check first:
`docker buildx imagetools inspect <image>:<tag>` must list `linux/arm64`. Don't use
`platform: linux/amd64` emulation for databases: it is slow and unreliable. Note that ClamAV's
default `latest` tag is amd64-only; we use the multi-arch `-debian` tag.

**Login fails for `supportx_app`, Keycloak or Temporal after editing `.env`**
See section 5: the old password is still stored in the volume. Run `make dev-reset`.

**The sign-in page is Keycloak's own, not the SupportX one**
The realm still uses the `supportx` theme (`make keycloak-theme` says so), but the container no
longer sees the theme folder: on macOS a bind mount goes empty when its host folder is deleted and
created again (a branch switch can do that). `docker compose -f deploy/compose/docker-compose.yml
restart keycloak` mounts it again; no data is touched. `docker exec supportx-dev-keycloak-1 ls
/opt/keycloak/themes/supportx` must list `login`.

**OpenSearch fails with "max virtual memory areas vm.max_map_count is too low" (Linux only)**
Run `sudo sysctl -w vm.max_map_count=262144`. Docker Desktop on Mac and Windows already sets this.

## 7. Notes

- Image versions are pinned. Upgrade them deliberately: change the tag, run `make dev-up-full` and
  `make dev-check`.
- MinIO no longer publishes community images. The stack uses `pgsty/minio`, a maintained community
  build of the same open-source code, for dev only. The production object-store choice is tracked
  in ADR-012.
- Temporal's `auto-setup` image stopped at 1.29.7 (newer server versions ship without it). It is
  fine for dev; how Temporal is deployed in real environments is decided in WP-014.

## Continuous integration on docs-only changes

Every pull request gets all required checks, also when it changes only `docs/` or Markdown: the
heavy jobs (the dev stack with end-to-end tests, the cluster images) start with a "changes" step
(`.github/actions/changes`) and finish at once with "skipped: docs-only change". A new push to a
pull request cancels that pull request's older runs; runs on `main` and nightly runs are never
cancelled.
