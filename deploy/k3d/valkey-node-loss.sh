#!/usr/bin/env bash
# The Valkey node-loss test (WP-014b, ADR-038) on the four-node k3d cluster with values-ha.yaml,
# run after ha-smoke.sh, so the master is the replica that smoke promoted (a set that has
# already failed over once):
#   1. sign in as a dev user through the BFF and save a preference (a real write);
#   2. wait (60 s) until Sentinel has settled: every sentinel knows the other two, names the same
#      master and lists two healthy replicas;
#   3. find the Valkey master and its node. If that node also holds PostgreSQL's primary, Sentinel
#      first hands the master to another pod (SENTINEL FAILOVER), so only Valkey is under test
#      (the database's failover is node-loss.sh's); then it settles again;
#   4. stop that node (k3d node stop), as a node that loses power, once cluster DNS is sure to
#      survive it (two CoreDNS copies, deploy/k3s/cluster-dns-ha.sh);
#   5. within 60 s the live sentinels name one new master on a live node; within 120 s more the
#      same session's write succeeds (the stopped node's API copy keeps its endpoints until
#      Kubernetes marks the node NotReady, about 50 s);
#   6. the node starts again: within 300 s the old master is a replica, exactly one master runs,
#      and every sentinel lists two healthy replicas; the database is back to three ready
#      instances and cluster DNS to two nodes, so node-loss.sh starts on a settled cluster.
# Whatever happens, the stopped node is started again (trap). Needs: make cluster-up-ha deploy-ha.
# Prints no secret.
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
  # Never leave a node stopped (a local cluster is reused, and node-loss.sh runs next).
  if [ -n "$STOPPED" ]; then
    echo "starting $STOPPED again (cleanup)"
    k3d node start "$STOPPED" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

pg() { kubectl -n "$NAMESPACE" get "clusters.postgresql.cnpg.io/$PG_CLUSTER" -o "jsonpath=$1"; }
three_ready() { [ "$(pg '{.status.readyInstances}')" = 3 ]; }
valkey_ready() {
  kubectl -n "$NAMESPACE" wait --for=condition=Ready pod -l app.kubernetes.io/component=valkey \
    --timeout=5s >/dev/null
}
# The live sentinels (pods off the stopped node) all name the same master, not the old one, and
# it runs on a live node.
failed_over() {  # failed_over <old master> <stopped node>
  local pod found="" this
  for pod in $VALKEY_PODS; do
    [ "$(node_of "$pod")" = "$2" ] && continue
    this="$(master_of "$pod")"
    [ -n "$this" ] && [ "$this" != "$1" ] || return 1
    [ -z "$found" ] || [ "$this" = "$found" ] || return 1
    found="$this"
  done
  [ -n "$found" ] && [ "$(node_of "$found")" != "$2" ]
}
rejoined() {  # rejoined <old master>: a replica again, and exactly one master
  local pod masters=0
  [ "$(role_of "$1")" = slave ] || return 1
  for pod in $VALKEY_PODS; do
    [ "$(role_of "$pod")" = master ] && masters=$((masters + 1))
  done
  [ "$masters" = 1 ]
}
dns_two_nodes() {
  [ "$(kubectl -n kube-system get pods -l k8s-app=kube-dns -o json | jq -r '[.items[]
    | select(.metadata.deletionTimestamp == null)
    | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))
    | .spec.nodeName] | unique | length')" -ge 2 ]
}

echo "== sign in as $USER_NAME through the BFF; save a preference"
sign_in "$USER_NAME"
save_locale null || { echo "the write failed before any node was stopped"; exit 1; }
echo "signed in; the write works"

echo "== Sentinel settles"
wait_settled 60 || exit 1
master="$(master_of supportx-valkey-0 || true)"
[ -n "$master" ] || { echo "the sentinels name no master"; exit 1; }
node="$(node_of "$master")"
primary="$(pg '{.status.currentPrimary}')"
pg_node="$(node_of "$primary")"
echo "Valkey master $master on $node; PostgreSQL primary $primary on $pg_node"

if [ "$node" = "$pg_node" ]; then
  # Keep the database out of this test: Sentinel moves the master instead (any other Valkey pod
  # is on another node: hard anti-affinity). No CloudNativePG plugin needed in the job.
  echo "== the master shares $node with PostgreSQL's primary: Sentinel hands it to another pod"
  vcli "$master" sentinel SENTINEL FAILOVER supportx >/dev/null ||
    { echo "SENTINEL FAILOVER was refused"; exit 1; }
  moved=""
  for _ in $(seq 1 20); do
    moved="$(master_of supportx-valkey-0 || true)"
    [ -n "$moved" ] && [ "$moved" != "$master" ] && break
    sleep 3
  done
  if [ -z "$moved" ] || [ "$moved" = "$master" ]; then
    echo "Sentinel did not move the master within 60 s"; exit 1
  fi
  # The new master and the demoted pod pass ready.sh's gate in their new roles first.
  until_ok 120 valkey_ready >/dev/null || { echo "Valkey pods not Ready after the hand-over"; exit 1; }
  wait_settled 60 || exit 1
  master="$moved"
  node="$(node_of "$master")"
  [ "$node" != "$pg_node" ] || { echo "the new master $master is still on $pg_node"; exit 1; }
  echo "Valkey master now $master on $node"
fi
case "$node" in
  *agent*) ;;
  *) echo "the master $master is on $node, not an agent: the server taint is missing"; exit 1 ;;
esac
dns_guard "$node" || exit 1

echo "== stop $node (Valkey master $master; also on it:" \
  "$(kubectl -n "$NAMESPACE" get pods --field-selector "spec.nodeName=$node" -o name | sed 's#pod/##' | tr '\n' ' '))"
STOPPED="$node"
k3d node stop "$node"

took="$(until_ok 60 failed_over "$master" "$node")" ||
  { echo "the live sentinels named no new master on a live node within 60 s"
    for pod in $VALKEY_PODS; do
      [ "$(node_of "$pod")" = "$node" ] && continue
      echo "  $pod's sentinel names: $(master_of "$pod" || true)"
    done
    exit 1; }
for pod in $VALKEY_PODS; do
  [ "$(node_of "$pod")" = "$node" ] && continue
  promoted="$(master_of "$pod" || true)"
  break
done
echo "Sentinel promoted $promoted (on $(node_of "$promoted")) after ${took}s"
took="$(until_ok 120 save_locale '"ar"')" ||
  { echo "the session or the write did not come back within 120 s (last answer: $(head -c 300 "$BODY"))"; exit 1; }
echo "the same session writes again after ${took}s more"

echo "== $node starts again"
k3d node start "$node"
STOPPED=""
kubectl wait --for=condition=Ready "node/$node" --timeout=300s
started=$SECONDS
kubectl -n "$NAMESPACE" wait --for=condition=Ready "pod/$master" --timeout=300s
budget=$((300 - (SECONDS - started)))
[ "$budget" -gt 0 ] || budget=1
took="$(until_ok "$budget" rejoined "$master")" ||
  { echo "$master is $(role_of "$master" || true), not a replica with one master, within 300 s of its node's return"; exit 1; }
echo "$master is a replica again; one master"
budget=$((300 - (SECONDS - started)))
[ "$budget" -gt 0 ] || budget=1
wait_settled "$budget" || exit 1
save_locale null || { echo "the write failed after the node returned"; exit 1; }

# Settled for node-loss.sh, which runs next: the database and cluster DNS whole again.
took="$(until_ok 600 three_ready)" ||
  { echo "the database did not get back to three ready instances: $(pg '{.status.phase}')"; exit 1; }
took="$(until_ok 120 dns_two_nodes)" || { echo "cluster DNS is not back on two nodes"; exit 1; }
echo "Valkey node-loss test passed: the master's node lost, Sentinel promoted $promoted, the session kept writing, $master rejoined as a replica"
