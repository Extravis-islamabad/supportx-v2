#!/usr/bin/env bash
# The Valkey node-loss test (WP-014b, ADR-038) on the four-node k3d cluster with values-ha.yaml,
# run after ha-smoke.sh, so the master is the replica that smoke promoted (a set that has
# already failed over once):
#   1. sign in as a dev user through the BFF and save a preference (a real write);
#   2. wait (60 s) until Sentinel has settled: every sentinel knows the other two, names the same
#      master and lists two healthy replicas;
#   3. find the Valkey master and its node. If that node also holds PostgreSQL's primary, Sentinel
#      first hands the master to a pod on another node (SENTINEL FAILOVER, the other replica at
#      replica-priority 0 meanwhile), so only Valkey is under test (the database's failover is
#      node-loss.sh's); then it settles again;
#   4. stop that node (k3d node stop), as a node that loses power, once cluster DNS is sure to
#      survive it (two CoreDNS copies, deploy/k3s/cluster-dns-ha.sh);
#   5. within 90 s the live sentinels name one new master on a live node; within 120 s more the
#      same session's write succeeds (the stopped node's API copy keeps its endpoints until
#      Kubernetes marks the node NotReady, about 50 s);
#   6. the node starts again: within 300 s the old master is a replica, exactly one master runs,
#      and every sentinel lists two healthy replicas; the database is back to three ready
#      instances and cluster DNS to two nodes, so node-loss.sh starts on a settled cluster.
# VALKEY_NODE_LOSS_CASE=master-with-dns (make cluster-ha-valkey-node-loss-dns) is the worst case
# on purpose: the stopped node holds the Valkey master AND a CoreDNS copy, so the sentinels'
# lookups stall on the dead CoreDNS endpoint while they fail over (Cluster run 43148329223). The
# placement is forced, never left to chance: a CoreDNS copy is moved onto an agent without the
# database primary if none is there, and the master is handed to that agent's Valkey pod (the
# other replica's replica-priority set to 0 for the hand-over, so Sentinel can only pick it).
# Whatever happens, the stopped node is started again, cordons are lifted and replica priorities
# restored (trap). Needs: make cluster-up-ha deploy-ha. Prints no secret.
set -euo pipefail

NAMESPACE="${SUPPORTX_NAMESPACE:-supportx}"
PUBLIC_URL="${SUPPORTX_PUBLIC_URL:-http://supportx.localhost:8080}"
PG_CLUSTER="${SUPPORTX_PG_CLUSTER:-supportx-pg}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
USER_NAME="tech@demo.test"
COOKIES="$(mktemp)"  # the session's Cookie header, mode 600
BODY="$(mktemp)"     # the last API answer
STOPPED=""
CORDONED=""
CASE="${VALKEY_NODE_LOSS_CASE:-master}"
case "$CASE" in master|master-with-dns) ;; *) echo "unknown VALKEY_NODE_LOSS_CASE $CASE"; exit 2 ;; esac
# shellcheck source=deploy/k3d/ha-lib.sh
. "$ROOT/deploy/k3d/ha-lib.sh"
cleanup() {
  rm -f "$COOKIES" "$BODY" "$SETTLE_REASON"
  for n in $CORDONED; do kubectl uncordon "$n" >/dev/null 2>&1 || true; done
  for pod in $VALKEY_PODS; do vcli "$pod" valkey CONFIG SET replica-priority 100 >/dev/null 2>&1 || true; done
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
dns_nodes() {  # the nodes of ready, non-terminating CoreDNS pods, one per line
  kubectl -n kube-system get pods -l k8s-app=kube-dns -o json | jq -r '[.items[]
    | select(.metadata.deletionTimestamp == null)
    | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))
    | .spec.nodeName] | unique | .[]'
}
no_dns_pod_on() {  # no CoreDNS pod (any state) left on <node>
  [ -z "$(kubectl -n kube-system get pods -l k8s-app=kube-dns --field-selector "spec.nodeName=$1" -o name)" ]
}
dns_two_nodes() { [ "$(dns_nodes | grep -c .)" -ge 2 ]; }
is_master() { [ "$(master_of supportx-valkey-0 || true)" = "$1" ]; }
# Hand the master to <target>, deterministically: every other replica gets replica-priority 0
# (never promoted) for the hand-over; Sentinel reads it from their INFO within 10 s.
hand_master_to() {  # hand_master_to <current master> <target>
  local pod tries
  for tries in 1 2 3; do
    for pod in $VALKEY_PODS; do
      [ "$pod" = "$1" ] || [ "$pod" = "$2" ] && continue
      vcli "$pod" valkey CONFIG SET replica-priority 0 >/dev/null
    done
    sleep 12
    vcli "$1" sentinel SENTINEL FAILOVER supportx >/dev/null || true
    if until_ok 60 is_master "$2" >/dev/null; then break; fi
    echo "hand-over to $2 not done (try $tries; the master is $(master_of supportx-valkey-0 || true))"
    [ "$tries" = 3 ] && return 1
    set -- "$(master_of supportx-valkey-0 || true)" "$2"
  done
  for pod in $VALKEY_PODS; do vcli "$pod" valkey CONFIG SET replica-priority 100 >/dev/null; done
  # The new master and the demoted pod pass ready.sh's gate in their new roles first.
  until_ok 120 valkey_ready >/dev/null || { echo "Valkey pods not Ready after the hand-over"; return 1; }
  wait_settled 60
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

target=""
if [ "$CASE" = master-with-dns ]; then
  # The worst case, forced: the master on an agent that also holds a CoreDNS copy (never the
  # database primary's node: only Valkey is under test).
  agents="$(kubectl get nodes -o name | sed 's#node/##' | grep agent | grep -vxF "$pg_node")"
  dns_agent="$(dns_nodes | grep -xF "$agents" | head -n 1 || true)"
  if [ -z "$dns_agent" ]; then
    # Both copies are on the server and the primary's node: move the primary node's copy onto a
    # free agent (both cordoned while the Deployment replaces it; anti-affinity keeps it off
    # the server's copy anyway).
    server="$(kubectl get nodes -o name | sed 's#node/##' | grep server | head -n 1)"
    echo "== no CoreDNS copy on an agent without the primary: moving the copy off $pg_node"
    CORDONED="$pg_node $server"
    for n in $CORDONED; do kubectl cordon "$n" >/dev/null; done
    kubectl -n kube-system delete pod -l k8s-app=kube-dns --field-selector "spec.nodeName=$pg_node" --wait=false
    until_ok 180 no_dns_pod_on "$pg_node" >/dev/null ||
      { echo "the CoreDNS copy on $pg_node did not go"; exit 1; }
    until_ok 180 dns_two_nodes >/dev/null || { echo "CoreDNS not back on two nodes after the move"; exit 1; }
    for n in $CORDONED; do kubectl uncordon "$n" >/dev/null; done
    CORDONED=""
    dns_agent="$(dns_nodes | grep -xF "$agents" | head -n 1 || true)"
    [ -n "$dns_agent" ] || { echo "no CoreDNS copy on an agent without the primary after the move: $(dns_nodes | tr '\n' ' ')"; exit 1; }
  fi
  for pod in $VALKEY_PODS; do [ "$(node_of "$pod")" = "$dns_agent" ] && target="$pod"; done
  [ -n "$target" ] || { echo "no Valkey pod on $dns_agent"; exit 1; }
  echo "worst case: the master goes to $target, on $dns_agent with a CoreDNS copy"
elif [ "$node" = "$pg_node" ]; then
  # Keep the database out of this test: the master goes to a pod on another node (hard
  # anti-affinity: every other Valkey pod is). No CloudNativePG plugin needed in the job.
  for pod in $VALKEY_PODS; do
    [ "$pod" != "$master" ] && [ "$(node_of "$pod")" != "$pg_node" ] && { target="$pod"; break; }
  done
  echo "== the master shares $node with PostgreSQL's primary: it goes to $target"
fi
if [ -n "$target" ] && [ "$target" != "$master" ]; then
  echo "== Sentinel hands the master from $master to $target"
  hand_master_to "$master" "$target" || { echo "Sentinel did not hand the master to $target"; exit 1; }
  master="$target"
  node="$(node_of "$master")"
  echo "Valkey master now $master on $node"
fi
[ "$node" != "$pg_node" ] || { echo "the master $master is on $pg_node with the database primary"; exit 1; }
if [ "$CASE" = master-with-dns ]; then
  dns_nodes | grep -qxF "$node" || { echo "worst case not reached: no CoreDNS copy on $node"; exit 1; }
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

# 90 s, not 60 (the coordinator, #425): after a node loss the sentinels stall on lookups that
# reach the lost node's CoreDNS endpoint (until it drops, about 20 s with the shipped grace
# period); Sentinel resolves synchronously, so a stall over 2 s puts it in TILT, which lasts a
# fixed 30 s (not configurable). Failover then takes about 50 s (runs 43153098860 and
# 43157246881: 37-54 s). NodeLocal DNSCache, the next lane B PR, removes the stall and brings
# these back to 60 s or less.
PROMOTE_BUDGET=90
took="$(until_ok "$PROMOTE_BUDGET" failed_over "$master" "$node")" ||
  { echo "the live sentinels named no new master on a live node within ${PROMOTE_BUDGET} s"
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
  { echo "the session or the write did not come back within 120 s (last answer: $(head -c 300 "$BODY"))"; show_write_trace; exit 1; }
echo "the same session writes again after ${took}s more"
show_write_trace

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
write_after_return || { echo "the session did not write again within 30 s of the node's return (ingress ready first)"; exit 1; }

# Settled for node-loss.sh, which runs next: the database and cluster DNS whole again.
took="$(until_ok 600 three_ready)" ||
  { echo "the database did not get back to three ready instances: $(pg '{.status.phase}')"; exit 1; }
took="$(until_ok 120 dns_two_nodes)" || { echo "cluster DNS is not back on two nodes"; exit 1; }
echo "Valkey node-loss test ($CASE) passed: the master's node lost, Sentinel promoted $promoted, the session kept writing, $master rejoined as a replica"
