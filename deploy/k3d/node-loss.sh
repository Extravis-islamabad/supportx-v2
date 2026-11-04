#!/usr/bin/env bash
# The node-loss test (WP-014b, plan decision 1b) on the four-node k3d cluster with values-ha.yaml:
#   1. sign in as a dev user through the BFF and save a preference (a real write);
#   2. stop the agent node that holds PostgreSQL's primary, as a node that loses power: every
#      pod on it goes at once (copies of the API, web, Keycloak, NATS and Valkey too);
#   3. CloudNativePG promotes a standby on another node;
#   4. the same session still works and the same write succeeds, through the public URL;
#   5. the node starts again: its database rejoins as a standby (one primary, three ready).
# The server node never runs our pods (cluster-ha.yaml taints it), so any agent may be stopped
# without losing the control plane. Needs: make cluster-up-ha deploy-ha. Prints no secret.
set -euo pipefail

NAMESPACE="${SUPPORTX_NAMESPACE:-supportx}"
PUBLIC_URL="${SUPPORTX_PUBLIC_URL:-http://supportx.localhost:8080}"
PG_CLUSTER="${SUPPORTX_PG_CLUSTER:-supportx-pg}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REALM="$ROOT/deploy/helm/supportx/files/keycloak/dev/supportx-realm.json"
USER_NAME="tech@demo.test"
COOKIES="$(mktemp)"  # the session's Cookie header, mode 600
BODY="$(mktemp)"     # the last API answer
STOPPED=""
cleanup() {
  rm -f "$COOKIES" "$BODY"
  # Never leave a node stopped (a local cluster is reused).
  if [ -n "$STOPPED" ]; then k3d node start "$STOPPED" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

pg() { kubectl -n "$NAMESPACE" get "clusters.postgresql.cnpg.io/$PG_CLUSTER" -o "jsonpath=$1"; }
api() {  # api METHOD PATH [curl args...]: prints the status; the body goes to $BODY
  local method="$1" path="$2"
  shift 2
  curl -s -m 10 -X "$method" -o "$BODY" -w '%{http_code}' -H "Cookie: $(cat "$COOKIES")" \
    -H 'X-SupportX-Client: console' "$@" "$PUBLIC_URL/api/v1$path" || echo 000
}
save_locale() {  # save_locale <"ar" | null>: 0 once the API stored it
  local value="$1" status me_id csrf version
  status="$(api GET /auth/me)"
  [ "$status" = 200 ] || return 1
  me_id="$(jq -r .user.id "$BODY")"
  csrf="$(jq -r .csrf_token "$BODY")"
  [ "$(api GET "/users/$me_id")" = 200 ] || return 1
  version="$(jq -r .version "$BODY")"
  status="$(api PATCH "/users/$me_id" -H 'Content-Type: application/json' \
    -H "If-Match: \"$version\"" -H "X-CSRF-Token: $csrf" -d "{\"ui_locale\": $value}")"
  [ "$status" = 200 ] && [ "$(jq -c .ui_locale "$BODY")" = "$value" ]
}
promoted() { [ "$(pg '{.status.currentPrimary}')" != "$1" ]; }
three_ready() { [ "$(pg '{.status.readyInstances}')" = 3 ]; }
until_ok() {  # until_ok <seconds> <command...>: retry every 3 s; the seconds it took
  local limit="$1" started=$SECONDS
  shift
  while ! "$@" 2>/dev/null; do
    [ $((SECONDS - started)) -ge "$limit" ] && return 1
    sleep 3
  done
  echo $((SECONDS - started))
}

echo "== sign in as $USER_NAME through the BFF; save a preference"
HA_LOGIN_PASSWORD="$(jq -r --arg u "$USER_NAME" '.users[] | select(.username == $u) | .credentials[0].value' "$REALM")" \
  uv run --project "$ROOT/backend" python "$ROOT/deploy/k3d/ha_login.py" "$PUBLIC_URL" "$USER_NAME" "$COOKIES"
save_locale null || { echo "the write failed before any node was stopped"; exit 1; }
echo "signed in; the write works"

primary="$(pg '{.status.currentPrimary}')"
node="$(kubectl -n "$NAMESPACE" get pod "$primary" -o jsonpath='{.spec.nodeName}')"
case "$node" in
  *agent*) ;;
  *) echo "the primary $primary is on $node, not an agent: the server taint is missing"; exit 1 ;;
esac
echo "== stop $node (PostgreSQL primary $primary; also on it:" \
  "$(kubectl -n "$NAMESPACE" get pods --field-selector "spec.nodeName=$node" -o name | sed 's#pod/##' | tr '\n' ' '))"
STOPPED="$node"
k3d node stop "$node"

took="$(until_ok 300 promoted "$primary")" ||
  { echo "no standby promoted within 300 s"; exit 1; }
echo "promoted after ${took}s: $(pg '{.status.currentPrimary}')"
took="$(until_ok 300 save_locale '"ar"')" ||
  { echo "the session or the write did not come back within 300 s (last answer: $(head -c 300 "$BODY"))"; exit 1; }
echo "the same session writes again after ${took}s more"

echo "== $node starts again"
k3d node start "$node"
STOPPED=""
kubectl wait --for=condition=Ready "node/$node" --timeout=300s
took="$(until_ok 600 three_ready)" ||
  { echo "the database did not get back to three ready instances: $(pg '{.status.phase}')"; exit 1; }
echo "three ready database instances after ${took}s; primary $(pg '{.status.currentPrimary}')"
save_locale null || { echo "the write failed after the node returned"; exit 1; }
echo "node-loss test passed: one agent lost, the database failed over, the session kept writing"
