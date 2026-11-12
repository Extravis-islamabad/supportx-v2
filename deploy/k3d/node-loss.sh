#!/usr/bin/env bash
# The node-loss test (WP-014b, plan decision 1b) on the four-node k3d cluster with values-ha.yaml:
#   1. sign in as a dev user through the BFF and save a preference (a real write);
#   2. wait (60 s) until Valkey's sentinels have settled (ha-lib.sh) and check cluster DNS
#      survives the node; then stop the agent node that holds PostgreSQL's primary, as a node
#      that loses power: every pod on it goes at once (copies of the API, web, Keycloak, NATS and
#      Valkey too);
#   3. CloudNativePG promotes a standby on another node;
#   4. the same session still works and the same write succeeds, through the public URL (and
#      which Valkey pod is master then is printed);
#   5. the node starts again: its database rejoins as a standby (one primary, three ready).
# The server node never runs our pods (cluster-ha.yaml taints it), so any agent may be stopped
# without losing the control plane. Needs: make cluster-up-ha deploy-ha. Prints no secret.
set -euo pipefail

NAMESPACE="${SUPPORTX_NAMESPACE:-supportx}"
PUBLIC_URL="${SUPPORTX_PUBLIC_URL:-http://supportx.localhost:8080}"
PG_CLUSTER="${SUPPORTX_PG_CLUSTER:-supportx-pg}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
USER_NAME="tech@demo.test"
COOKIES="$(mktemp)"  # the session's Cookie header, mode 600
BODY="$(mktemp)"     # the last API answer
STOPPED=""
# shellcheck source=deploy/k3d/ha-lib.sh
. "$ROOT/deploy/k3d/ha-lib.sh"
cleanup() {
  rm -f "$COOKIES" "$BODY" "$SETTLE_REASON"
  # Never leave a node stopped (a local cluster is reused).
  if [ -n "$STOPPED" ]; then k3d node start "$STOPPED" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

pg() { kubectl -n "$NAMESPACE" get "clusters.postgresql.cnpg.io/$PG_CLUSTER" -o "jsonpath=$1"; }
promoted() { [ "$(pg '{.status.currentPrimary}')" != "$1" ]; }
three_ready() { [ "$(pg '{.status.readyInstances}')" = 3 ]; }

echo "== sign in as $USER_NAME through the BFF; save a preference"
sign_in "$USER_NAME"
save_locale null || { echo "the write failed before any node was stopped"; exit 1; }
echo "signed in; the write works"

primary="$(pg '{.status.currentPrimary}')"
node="$(kubectl -n "$NAMESPACE" get pod "$primary" -o jsonpath='{.spec.nodeName}')"
case "$node" in
  *agent*) ;;
  *) echo "the primary $primary is on $node, not an agent: the server taint is missing"; exit 1 ;;
esac
# Settled first: a node stopped while Sentinel is still converging (after the earlier tests'
# failovers) can leave it without a quorum or a promotable replica. Then cluster DNS must
# survive this node (Cluster run 43082299609 stopped the node with the only CoreDNS copy).
wait_settled 60 || exit 1
dns_guard "$node" || exit 1
echo "== stop $node (PostgreSQL primary $primary; also on it:" \
  "$(kubectl -n "$NAMESPACE" get pods --field-selector "spec.nodeName=$node" -o name | sed 's#pod/##' | tr '\n' ' '))"
STOPPED="$node"
k3d node stop "$node"

took="$(until_ok 300 promoted "$primary")" ||
  { echo "no standby promoted within 300 s"; exit 1; }
echo "promoted after ${took}s: $(pg '{.status.currentPrimary}')"
took="$(until_ok 300 save_locale '"ar"')" ||
  { echo "the session or the write did not come back within 300 s (last answer: $(head -c 300 "$BODY"))"; show_write_trace; exit 1; }
echo "the same session writes again after ${took}s more"
show_write_trace
for pod in $VALKEY_PODS; do
  [ "$(node_of "$pod")" = "$node" ] && continue
  echo "Valkey master now: $(master_of "$pod" || true) (as $pod's sentinel names it)"
  break
done

echo "== $node starts again"
k3d node start "$node"
STOPPED=""
kubectl wait --for=condition=Ready "node/$node" --timeout=300s
took="$(until_ok 600 three_ready)" ||
  { echo "the database did not get back to three ready instances: $(pg '{.status.phase}')"; exit 1; }
echo "three ready database instances after ${took}s; primary $(pg '{.status.currentPrimary}')"
save_locale null || { echo "the write failed after the node returned"; exit 1; }
echo "node-loss test passed: one agent lost, the database failed over, the session kept writing"
