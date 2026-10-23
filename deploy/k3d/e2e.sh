#!/usr/bin/env bash
# Playwright journeys against the k3d cluster (make cluster-e2e; nightly CI, WP-014).
#
#   deploy/k3d/e2e.sh [playwright args...]     e.g. deploy/k3d/e2e.sh tests/login.spec.ts
#
# The browser uses the public URL like a user would. The suite's helpers (Keycloak admin API,
# backend fixtures, plan changes) get the cluster's addresses and dev secrets through
# SUPPORTX_E2E_* / SUPPORTX_* variables; the database through the dev profile's NodePort on this
# machine's loopback. Nothing is written to disk; only the cluster's own dev data is touched.
set -euo pipefail

NAMESPACE="${SUPPORTX_NAMESPACE:-supportx}"
PUBLIC_URL="${SUPPORTX_PUBLIC_URL:-http://supportx.localhost:8080}"
PG_PORT="${SUPPORTX_E2E_PG_PORT:-25433}"   # k3d maps it to the dev NodePort
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

secret() {
  kubectl -n "$NAMESPACE" get secret supportx-app -o "jsonpath={.data.$1}" | base64 --decode
}

# The database through the dev-only NodePort (values-dev.yaml, deploy/k3d/cluster.yaml).
export SUPPORTX_CONSOLE_URL="$PUBLIC_URL"
export SUPPORTX_PORTAL_URL="$PUBLIC_URL/portal"
export SUPPORTX_E2E_KEYCLOAK_URL="$PUBLIC_URL/auth"
export SUPPORTX_E2E_KEYCLOAK_ADMIN_USER=admin
SUPPORTX_E2E_KEYCLOAK_ADMIN_PASSWORD="$(secret keycloak-admin-password)"
SUPPORTX_E2E_CENTRIFUGO_TOKEN_SECRET="$(secret centrifugo-token-secret)"
SUPPORTX_MIGRATION_DATABASE_URL="postgresql://supportx_migrator:$(secret migrator-db-password)@127.0.0.1:$PG_PORT/supportx"
export SUPPORTX_E2E_KEYCLOAK_ADMIN_PASSWORD SUPPORTX_E2E_CENTRIFUGO_TOKEN_SECRET SUPPORTX_MIGRATION_DATABASE_URL

cd "$ROOT/frontend"
pnpm --filter @supportx/e2e exec playwright test "$@"
