#!/usr/bin/env bash
# The HA smoke (WP-014b, ADR-038) on the four-node k3d cluster with values-ha.yaml:
#   1. sign in as a dev user through the BFF (a real session in Valkey);
#   2. kill the Valkey master's pod at once (no graceful stop), as a crashed server;
#   3. the same session cookie still works (Sentinel promoted a replica; the app followed it);
#   4. the StatefulSet starts that pod again under the same name: it comes back as a replica,
#      with exactly one master (the split-brain case ADR-038 rules out).
# Losing a whole node is the HA install's acceptance test (the e2e suite on this cluster, later
# in WP-014b): there the database fails over too, which this smoke keeps out of the picture.
# Needs: make cluster-up-ha deploy-ha. Prints no secret.
set -euo pipefail

NAMESPACE="${SUPPORTX_NAMESPACE:-supportx}"
PUBLIC_URL="${SUPPORTX_PUBLIC_URL:-http://supportx.localhost:8080}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REALM="$ROOT/deploy/helm/supportx/files/keycloak/dev/supportx-realm.json"
USER_NAME="tech@demo.test"
COOKIES="$(mktemp)"  # the session's Cookie header, mode 600; removed on exit
trap 'rm -f "$COOKIES"' EXIT

# valkey-cli inside a pod through the chart's own `vcli` (templates/valkey-ha.yaml common.sh): it
# holds the password and, with valkeyHa.tls on (values-ha.yaml), the TLS flags and the CA.
vcli() {  # vcli <pod> <container> <valkey-cli args...>
  local pod="$1" container="$2"
  shift 2
  kubectl -n "$NAMESPACE" exec "$pod" -c "$container" -- sh -c '. /scripts/common.sh; vcli "$@"' vcli "$@"
}
sentinel() {  # a sentinel's answer: the current master's pod name
  vcli "$1" sentinel -p 26379 SENTINEL get-master-addr-by-name supportx \
    2>/dev/null | head -n 1 | cut -d. -f1
}
role() {
  vcli "$1" valkey info replication 2>/dev/null | tr -d '\r' | sed -n 's/^role://p'
}
me() {
  curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $(cat "$COOKIES")" \
    -H 'X-SupportX-Client: console' "$PUBLIC_URL/api/v1/auth/me"
}

echo "== sign in as $USER_NAME through the BFF"
# ha_login.py follows the sign-in itself: the BFF's and Keycloak's cookies are Secure, which
# curl won't keep over http:// (browsers treat *.localhost as secure).
HA_LOGIN_PASSWORD="$(jq -r --arg u "$USER_NAME" '.users[] | select(.username == $u) | .credentials[0].value' "$REALM")" \
  uv run --project "$ROOT/backend" python "$ROOT/deploy/k3d/ha_login.py" "$PUBLIC_URL" "$USER_NAME" "$COOKIES"
[ "$(me)" = 200 ] || { echo "not signed in after the login flow"; exit 1; }
echo "signed in"

master="$(sentinel supportx-valkey-0)"
[ -n "$master" ] || { echo "the sentinels name no master"; exit 1; }
echo "== kill the Valkey master $master"
kubectl -n "$NAMESPACE" delete pod "$master" --grace-period=0 --force --wait=false
promoted=""
for _ in $(seq 1 90); do
  for pod in supportx-valkey-0 supportx-valkey-1 supportx-valkey-2; do
    [ "$pod" = "$master" ] && continue
    found="$(sentinel "$pod" || true)"
    if [ -n "$found" ] && [ "$found" != "$master" ]; then promoted="$found"; break 2; fi
  done
  sleep 2
done
[ -n "$promoted" ] || { echo "no replica promoted"; exit 1; }
echo "promoted: $promoted"
# Steady, not once: for a moment after the promotion a request can still reach an API copy that
# hasn't followed the new master. Five answers in a row, within two minutes.
steady=0
for _ in $(seq 1 120); do
  if [ "$(me)" = 200 ]; then steady=$((steady + 1)); else steady=0; fi
  [ "$steady" -ge 5 ] && break
  sleep 1
done
[ "$steady" -ge 5 ] || { echo "the session did not survive the failover"; exit 1; }
echo "the same session works after the failover"

echo "== $master starts again"
sleep 5  # the StatefulSet makes a new pod of that name
kubectl -n "$NAMESPACE" wait --for=condition=Ready "pod/$master" --timeout=300s
for _ in $(seq 1 60); do [ "$(role "$master")" = slave ] && break; sleep 2; done
[ "$(role "$master")" = slave ] || { echo "$master did not rejoin as a replica"; exit 1; }
masters=0
for pod in supportx-valkey-0 supportx-valkey-1 supportx-valkey-2; do
  [ "$(role "$pod")" = master ] && masters=$((masters + 1))
done
[ "$masters" = 1 ] || { echo "$masters masters: split brain"; exit 1; }
[ "$(me)" = 200 ] || { echo "the session was lost after the node returned"; exit 1; }
echo "HA smoke passed: failover, the session kept, the old master a replica, one master"
