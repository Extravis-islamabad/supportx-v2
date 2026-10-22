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

## 4. Services, ports and logins

All ports are bound to `127.0.0.1` only, so nothing is reachable from your network. They are in
the 2xxxx range to avoid clashing with other projects; each one can be changed in
`deploy/compose/.env`.

| Service | Set | Local address | Dev login (password variable in `.env`) |
|---|---|---|---|
| PostgreSQL 16 + pgvector | core | `localhost:25432`, databases `supportx`, `keycloak`, `temporal`, `temporal_visibility` | App: `supportx_app` / `SUPPORTX_APP_PASSWORD`. Migrations: `supportx_migrator` / `SUPPORTX_MIGRATOR_PASSWORD`. Admin: `postgres` / `POSTGRES_SUPERUSER_PASSWORD` |
| PgBouncer (transaction mode) | core | `localhost:26432`, database `supportx` | `supportx_app` / `SUPPORTX_APP_PASSWORD` |
| Valkey | core | `localhost:26379` | password `VALKEY_PASSWORD` (no username) |
| NATS + JetStream | core | `nats://localhost:24222`, monitoring <http://localhost:28222> | none (dev) |
| Keycloak (dev mode) | core | <http://localhost:28080> (admin console), health <http://localhost:28090/health> | `admin` / `KEYCLOAK_ADMIN_PASSWORD` |
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

### Database roles (why there are three)

- `supportx_app` is what the API and workers use. It is **not** a superuser, owns nothing and has
  **no `BYPASSRLS`**, so PostgreSQL row-level security always applies to it. This is what keeps one
  tenant's data invisible to another (CLAUDE.md rule a). `make dev-check` proves it.
- `supportx_migrator` owns the `supportx` database and schema; Alembic migrations run as this role.
  Tables it creates are automatically usable (read/write, no DDL) by `supportx_app`.
- `postgres` is the bootstrap superuser, used only by the init script and `dev-check`.

The app connects through PgBouncer (transaction pooling). Migrations, Keycloak and Temporal connect
to PostgreSQL directly.

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

**Apple Silicon: "no matching manifest for linux/arm64"**
All images in `docker-compose.yml` support arm64. If you add or upgrade one, check first:
`docker buildx imagetools inspect <image>:<tag>` must list `linux/arm64`. Don't use
`platform: linux/amd64` emulation for databases: it is slow and unreliable. Note that ClamAV's
default `latest` tag is amd64-only; we use the multi-arch `-debian` tag.

**Login fails for `supportx_app`, Keycloak or Temporal after editing `.env`**
See section 5: the old password is still stored in the volume. Run `make dev-reset`.

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
