#!/usr/bin/env bash
# The egress allow-list (WP-014b, networkPolicies.egress) on the k3d HA cluster, where
# values-ha-ci.yaml turns it on. From inside an API pod:
#   1. DNS and SupportX's own services (PgBouncer, Keycloak, NATS) answer;
#   2. an address outside the cluster does not, although this runner itself reaches it,
#      so the block is the policy and not a missing internet connection.
# Needs: make cluster-up-ha deploy-ha.
set -euo pipefail

NAMESPACE="${SUPPORTX_NAMESPACE:-supportx}"
OUTSIDE_HOST="${EGRESS_OUTSIDE_HOST:-1.1.1.1}"
OUTSIDE_PORT="${EGRESS_OUTSIDE_PORT:-443}"

reach() {  # reach <host> <port>: "open" or the reason it is not, from an API pod
  kubectl -n "$NAMESPACE" exec deploy/supportx-api -c api -- python -c '
import socket, sys
try:
    socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=5).close()
    print("open")
except OSError as error:
    print(type(error).__name__)
' "$1" "$2"
}

echo "== the runner reaches $OUTSIDE_HOST:$OUTSIDE_PORT (the control)"
if ! curl -s -o /dev/null -m 10 "https://$OUTSIDE_HOST:$OUTSIDE_PORT"; then
  echo "the runner itself has no route out: this check proves nothing here"; exit 1
fi

failed=0
for target in supportx-pg-pooler:5432 supportx-keycloak:8080 supportx-nats:4222; do
  got="$(reach "${target%%:*}" "${target##*:}")"
  echo "inside $target: $got"
  [ "$got" = open ] || failed=1
done
got="$(reach "$OUTSIDE_HOST" "$OUTSIDE_PORT")"
echo "outside $OUTSIDE_HOST:$OUTSIDE_PORT: $got"
[ "$got" != open ] || { echo "egress to the outside is open: the allow-list is not applied"; failed=1; }
[ "$failed" = 0 ] || exit 1
echo "egress check passed: DNS and the namespace reachable, the outside blocked"
