#!/usr/bin/env bash
# Proves every running dev-stack service really works (not just "container is up") and prints a
# PASS/FAIL table. Core services must be running; "full" services are checked when running and
# reported as SKIP otherwise. Read-only: the RLS probe runs inside a transaction that is rolled back.
# Exit code is non-zero if any check fails.
set -uo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
env_file="$here/.env"
if [[ ! -f "$env_file" ]]; then
  echo "deploy/compose/.env is missing; run 'make dev-init' first." >&2
  exit 2
fi
set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

compose=(docker compose --project-directory "$here" -f "$here/docker-compose.yml" --profile full)
running="$("${compose[@]}" ps --status running --services 2>/dev/null)"

results=()
failures=0

record() { # name, status, detail
  results+=("$1|$2|$3")
  [[ "$2" == "FAIL" ]] && failures=$((failures + 1))
  return 0
}

is_running() { grep -qx "$1" <<<"$running"; }

# check NAME SERVICE PROFILE EXPECT-DESCRIPTION -- command...
# Runs the command; PASS if it exits 0. Output (trimmed) becomes the detail on failure.
check() {
  local name="$1" service="$2" profile="$3" what="$4"
  shift 5
  if ! is_running "$service"; then
    if [[ "$profile" == "full" ]]; then
      record "$name" "SKIP" "$service not running (full profile)"
    else
      record "$name" "FAIL" "$service container is not running"
    fi
    return
  fi
  local out
  if out="$("$@" 2>&1)"; then
    record "$name" "PASS" "$what"
  else
    out="$(tr '\n' ' ' <<<"$out" | cut -c1-90)"
    record "$name" "FAIL" "${out:-$what failed}"
  fi
}

# psql inside the postgres container, as any role, over TCP so password auth is exercised.
psql_as() { # user password host port db sql
  "${compose[@]}" exec -T -e PGPASSWORD="$2" postgres \
    psql -X -v ON_ERROR_STOP=1 -At -h "$3" -p "$4" -U "$1" -d "$5" -c "$6"
}

expect() { # expected-output command...  (passes when output equals expected)
  local want="$1" got
  shift
  got="$("$@")" || return 1
  if [[ "$got" != "$want" ]]; then
    echo "expected '$want', got '$got'"
    return 1
  fi
}

http_ok() { curl -fsS --max-time 10 "$@" >/dev/null; }
http_grep() { # pattern curl-args...
  local pattern="$1" body
  shift
  body="$(curl -fsS --max-time 10 "$@")" || return 1
  grep -qE "$pattern" <<<"$body" || { echo "unexpected response: ${body:0:80}"; return 1; }
}

# --- PostgreSQL ---------------------------------------------------------------------------------
check "postgres: login as supportx_app" postgres core "SELECT 1 as supportx_app" -- \
  expect "supportx_app" psql_as supportx_app "$SUPPORTX_APP_PASSWORD" 127.0.0.1 5432 supportx \
  "SELECT current_user"

check "postgres: extensions" postgres core "vector, pgcrypto, citext installed" -- \
  expect "citext,pgcrypto,vector" psql_as supportx_app "$SUPPORTX_APP_PASSWORD" 127.0.0.1 5432 \
  supportx "SELECT string_agg(extname, ',' ORDER BY extname) FROM pg_extension
            WHERE extname IN ('vector','pgcrypto','citext')"

check "postgres: app role attributes" postgres core "not superuser, no BYPASSRLS, owns nothing" -- \
  expect "f|f|0|0|f" psql_as supportx_app "$SUPPORTX_APP_PASSWORD" 127.0.0.1 5432 supportx \
  "SELECT r.rolsuper, r.rolbypassrls,
          (SELECT count(*) FROM pg_class c WHERE c.relowner = r.oid),
          (SELECT count(*) FROM pg_database d WHERE d.datdba = r.oid),
          has_schema_privilege('public', 'CREATE')
     FROM pg_roles r WHERE r.rolname = current_user"

check "postgres: migrator owns supportx" postgres core "supportx_migrator owns db + schema" -- \
  expect "supportx_migrator|supportx_migrator" psql_as supportx_migrator \
  "$SUPPORTX_MIGRATOR_PASSWORD" 127.0.0.1 5432 supportx \
  "SELECT pg_get_userbyid(d.datdba), pg_get_userbyid(n.nspowner)
     FROM pg_database d, pg_namespace n
    WHERE d.datname = 'supportx' AND n.nspname = 'public'"

# Functional proof that RLS binds supportx_app: a throwaway table with a tenant policy, queried
# as supportx_app with tenant A, with tenant B and with no tenant. Everything is rolled back.
rls_probe() {
  "${compose[@]}" exec -T postgres psql -X -v ON_ERROR_STOP=1 -At -q \
    -U "$POSTGRES_SUPERUSER" -d supportx <<'SQL'
BEGIN;
CREATE TEMP TABLE devcheck_rls (tenant_id text NOT NULL, note text) ON COMMIT DROP;
INSERT INTO devcheck_rls VALUES ('tenant-a', 'a1'), ('tenant-b', 'b1');
ALTER TABLE devcheck_rls ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON devcheck_rls
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON devcheck_rls TO supportx_app;
SET LOCAL ROLE supportx_app;
SET LOCAL app.tenant_id = 'tenant-a';
SELECT 'a=' || count(*) FROM devcheck_rls;
SET LOCAL app.tenant_id = 'tenant-b';
SELECT 'b=' || string_agg(note, ',') FROM devcheck_rls;
RESET app.tenant_id;
SELECT 'none=' || count(*) FROM devcheck_rls;
SET LOCAL app.tenant_id = 'tenant-a';
SAVEPOINT cross_tenant_write;
DO $$ BEGIN
  INSERT INTO devcheck_rls VALUES ('tenant-b', 'smuggled');
  RAISE NOTICE 'unexpected';
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'blocked';
END $$;
SELECT 'write=blocked';
ROLLBACK;
SQL
}
rls_check() {
  local out
  out="$(rls_probe 2>&1)" || { echo "$out"; return 1; }
  out="$(tr '\n' ' ' <<<"$out")"
  [[ "$out" == *"a=1"* && "$out" == *"b=b1"* && "$out" == *"none=0"* \
    && "$out" == *"blocked"* && "$out" != *"unexpected"* ]] || { echo "$out"; return 1; }
}
check "postgres: RLS applies to app" postgres core "tenant A sees 1 row, none sees 0, cross write blocked" -- \
  rls_check

denied_elsewhere() {
  local out
  if out="$(psql_as supportx_app "$SUPPORTX_APP_PASSWORD" 127.0.0.1 5432 keycloak "SELECT 1" 2>&1)"; then
    echo "supportx_app could connect to the keycloak database"
    return 1
  fi
  grep -q "permission denied" <<<"$out" || { echo "$out"; return 1; }
}
check "postgres: app isolated from others" postgres core "supportx_app denied on keycloak db" -- \
  denied_elsewhere

# --- PgBouncer ----------------------------------------------------------------------------------
check "pgbouncer: query via pool" pgbouncer core "supportx_app through pgbouncer:6432" -- \
  expect "supportx_app" psql_as supportx_app "$SUPPORTX_APP_PASSWORD" pgbouncer 6432 supportx \
  "SELECT current_user"

check "pgbouncer: transaction mode" pgbouncer core "pool_mode = transaction" -- \
  "${compose[@]}" exec -T pgbouncer grep -qE '^pool_mode *= *transaction' /etc/pgbouncer/pgbouncer.ini

# --- Valkey -------------------------------------------------------------------------------------
check "valkey: PING" valkey core "PONG with password" -- \
  expect "PONG" "${compose[@]}" exec -T -e REDISCLI_AUTH="$VALKEY_PASSWORD" valkey valkey-cli ping

# --- NATS ---------------------------------------------------------------------------------------
check "nats: JetStream enabled" nats core "healthz ok, JetStream config present" -- \
  bash -c 'curl -fsS --max-time 5 "http://127.0.0.1:$1/healthz?js-enabled-only=true" | grep -q ok &&
           curl -fsS --max-time 5 "http://127.0.0.1:$1/jsz" | grep -q "\"max_memory\""' _ \
  "$NATS_MONITOR_PORT"

# --- Keycloak -----------------------------------------------------------------------------------
check "keycloak: health ready" keycloak core "/health/ready is UP" -- \
  http_grep '"status": ?"UP"' "http://127.0.0.1:$KEYCLOAK_MANAGEMENT_PORT/health/ready"
check "keycloak: master realm" keycloak core "OIDC discovery for master realm" -- \
  http_grep '"issuer"' "http://127.0.0.1:$KEYCLOAK_PORT/realms/master/.well-known/openid-configuration"

# --- Centrifugo ---------------------------------------------------------------------------------
check "centrifugo: health" centrifugo core "/health responds" -- \
  http_ok "http://127.0.0.1:$CENTRIFUGO_PORT/health"
check "centrifugo: server API" centrifugo core "info call with API key" -- \
  http_grep '"nodes"' -X POST -H "X-API-Key: $CENTRIFUGO_API_KEY" -H 'Content-Type: application/json' \
  -d '{}' "http://127.0.0.1:$CENTRIFUGO_PORT/api/info"

# --- MinIO --------------------------------------------------------------------------------------
check "minio: live" minio core "/minio/health/live" -- \
  http_ok "http://127.0.0.1:$MINIO_API_PORT/minio/health/live"
check "minio: bucket exists" minio core "bucket '$MINIO_BUCKET' exists" -- \
  "${compose[@]}" run --rm --no-deps -T minio-init stat "local/$MINIO_BUCKET"

# --- Mailpit ------------------------------------------------------------------------------------
check "mailpit: web UI + API" mailpit core "web UI and /api/v1/info respond" -- \
  bash -c 'curl -fsS --max-time 5 "http://127.0.0.1:$1/" >/dev/null &&
           curl -fsS --max-time 5 "http://127.0.0.1:$1/api/v1/info" | grep -q "\"Version\""' _ \
  "$MAILPIT_WEB_PORT"
check "mailpit: SMTP" mailpit core "SMTP banner on 127.0.0.1:$MAILPIT_SMTP_PORT" -- \
  bash -c 'exec 3<>"/dev/tcp/127.0.0.1/$1" && read -r -t 5 banner <&3 && [[ "$banner" == 220* ]]' _ \
  "$MAILPIT_SMTP_PORT"

# --- Full profile -------------------------------------------------------------------------------
check "temporal: cluster health" temporal full "frontend SERVING" -- \
  "${compose[@]}" exec -T temporal sh -c 'tctl --address "$(hostname -i):7233" cluster health | grep -q SERVING'
check "temporal: default namespace" temporal full "namespace 'default' registered" -- \
  "${compose[@]}" exec -T temporal sh -c 'tctl --address "$(hostname -i):7233" --namespace default namespace describe | grep -q default'
check "temporal-ui: web UI" temporal-ui full "UI responds" -- \
  http_ok "http://127.0.0.1:$TEMPORAL_UI_PORT/"
check "opensearch: cluster health" opensearch full "status green or yellow" -- \
  http_grep '"status":"(green|yellow)"' "http://127.0.0.1:$OPENSEARCH_PORT/_cluster/health"
check "clickhouse: query" clickhouse full "SELECT 1 as $CLICKHOUSE_USER" -- \
  expect "1" curl -fsS --max-time 10 -u "$CLICKHOUSE_USER:$CLICKHOUSE_PASSWORD" \
  "http://127.0.0.1:$CLICKHOUSE_HTTP_PORT/?query=SELECT%201"
check "clickhouse: database" clickhouse full "database $CLICKHOUSE_DB exists" -- \
  expect "1" curl -G -fsS --max-time 10 -u "$CLICKHOUSE_USER:$CLICKHOUSE_PASSWORD" \
  --data-urlencode "query=SELECT count() FROM system.databases WHERE name = '$CLICKHOUSE_DB'" \
  "http://127.0.0.1:$CLICKHOUSE_HTTP_PORT/"
check "clamav: clamd PING" clamav full "PONG on 127.0.0.1:$CLAMAV_PORT" -- \
  bash -c 'exec 3<>"/dev/tcp/127.0.0.1/$1" && printf "zPING\0" >&3 && read -r -d "" -t 10 r <&3; [[ "$r" == PONG* ]]' _ \
  "$CLAMAV_PORT"

# --- Report -------------------------------------------------------------------------------------
printf '\n%-36s %-6s %s\n' "CHECK" "RESULT" "DETAIL"
printf '%-36s %-6s %s\n' "-----" "------" "------"
for row in "${results[@]}"; do
  IFS='|' read -r name status detail <<<"$row"
  printf '%-36s %-6s %s\n' "$name" "$status" "$detail"
done
passed=$(printf '%s\n' "${results[@]}" | grep -c '|PASS|')
skipped=$(printf '%s\n' "${results[@]}" | grep -c '|SKIP|')
printf '\n%d passed, %d failed, %d skipped.\n' "$passed" "$failures" "$skipped"
if ((failures > 0)); then
  echo "dev-check: FAIL"
  exit 1
fi
echo "dev-check: PASS"
