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
JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT

sentinel() {  # a sentinel's answer: the current master's pod name
  kubectl -n "$NAMESPACE" exec "$1" -c sentinel -- sh -c \
    'REDISCLI_AUTH="$VALKEY_PASSWORD" valkey-cli -p 26379 --no-auth-warning SENTINEL get-master-addr-by-name supportx' \
    2>/dev/null | head -n 1 | cut -d. -f1
}
role() {
  kubectl -n "$NAMESPACE" exec "$1" -c valkey -- sh -c \
    'REDISCLI_AUTH="$VALKEY_PASSWORD" valkey-cli --no-auth-warning info replication' \
    2>/dev/null | tr -d '\r' | sed -n 's/^role://p'
}
# The jar's cookies as one header. The BFF marks its cookie Secure, which curl won't send over
# http:// itself (browsers treat *.localhost as secure). Names and values only; never printed.
cookies() { awk -F'\t' 'NF >= 7 { printf "%s%s=%s", (n++ ? "; " : ""), $6, $7 }' "$JAR"; }
me() {
  curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $(cookies)" -H 'X-SupportX-Client: console' \
    "$PUBLIC_URL/api/v1/auth/me"
}

echo "== sign in as $USER_NAME through the BFF"
password="$(jq -r --arg u "$USER_NAME" '.users[] | select(.username == $u) | .credentials[0].value' "$REALM")"
page="$(curl -s -c "$JAR" -b "$JAR" -L "$PUBLIC_URL/api/v1/auth/login?app=console&returnTo=/")"
action="$(printf '%s' "$page" | grep -o 'id="kc-form-login"[^>]*action="[^"]*"' | sed 's/.*action="//; s/"$//; s/&amp;/\&/g')"
[ -n "$action" ] || { echo "no Keycloak login form"; exit 1; }
ended="$(curl -s -c "$JAR" -b "$JAR" -L -o /dev/null -w '%{http_code} %{url_effective}' \
  --data-urlencode "username=$USER_NAME" --data-urlencode "password=$password" "$action")"
if [ "$(me)" != 200 ]; then
  # What can be said without a secret: where the flow ended, and which cookies it holds.
  echo "not signed in after the login flow (ended: ${ended%%\?*}; /auth/me: $(me))"
  echo "cookies held: $(awk -F'\t' 'NF >= 7 { printf "%s ", $6 }' "$JAR")"
  exit 1
fi
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
for _ in $(seq 1 60); do [ "$(me)" = 200 ] && break; sleep 2; done
[ "$(me)" = 200 ] || { echo "the session did not survive the failover"; exit 1; }
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
