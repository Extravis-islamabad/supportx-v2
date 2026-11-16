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
#   5. live updates resume: the fan-out (one copy by design, ADR-023) is ready on a live node
#      (it moves when its node was the stopped one: ha.fastEvictionSeconds), and a write made
#      after that reaches it through JetStream (its durable consumer acknowledges past it);
#   6. the node starts again: its database rejoins as a standby (one primary, three ready).
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

# The fan-out's durable consumer (backend/workers/realtime_fanout/runner.py CONSUMER_NAME) on the
# events stream (app/shared/events/subjects.py). Read from NATS's monitoring endpoint inside each
# server's own container (127.0.0.1:8222): no NATS credentials, no NetworkPolicy in the way.
FANOUT_CONSUMER="realtime__fanout"
EVENTS_STREAM="SUPPORTX_EVENTS"
FANOUT_LABELS="app.kubernetes.io/part-of=supportx,app.kubernetes.io/component=fanout"
FANOUT_BUDGET=90
ready_pods() {  # ready_pods <label selector> <node to leave out>: ready pods elsewhere
  kubectl -n "$NAMESPACE" get pods -l "$1" -o json | jq -r --arg n "$2" '.items[]
    | select(.metadata.deletionTimestamp == null)
    | select(.spec.nodeName != $n)
    | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))
    | .metadata.name'
}
fanout_ready_off() { [ -n "$(ready_pods "$FANOUT_LABELS" "$1")" ]; }
# Why a fan-out copy off the stopped node is not ready (three runs failed here with only the dead
# copy's logs to read, 43307414807, 131530642943, 43462162931): for each copy elsewhere, its
# conditions and recent events, its containers' logs, and its own /readyz answer through the API
# server's pod proxy. Never fails the caller.
fanout_diagnose() {  # fanout_diagnose <stopped node>
  local pod port
  for pod in $(kubectl -n "$NAMESPACE" get pods -l "$FANOUT_LABELS" -o json |
    jq -r --arg n "$1" '.items[] | select(.spec.nodeName != $n) | .metadata.name'); do
    echo "== fan-out copy $pod (not on $1)"
    kubectl -n "$NAMESPACE" get pod "$pod" -o json |
      jq -r '"phase \(.status.phase); started \(.status.startTime // "-")",
        (.status.conditions[]? | "  \(.type)=\(.status) \(.reason // "") \(.message // "")"),
        (.status.containerStatuses[]? | "  \(.name): ready=\(.ready) restarts=\(.restartCount) \(.state | keys | first)")' || true
    kubectl -n "$NAMESPACE" get events --field-selector "involvedObject.name=$pod" \
      --sort-by=.lastTimestamp -o custom-columns=AT:.lastTimestamp,REASON:.reason,MSG:.message |
      tail -n 15 || true
    kubectl -n "$NAMESPACE" logs "$pod" --all-containers --tail=80 --prefix || true
    port="$(kubectl -n "$NAMESPACE" get pod "$pod" -o json |
      jq -r '[.spec.containers[].ports[]? | select(.name == "metrics") | .containerPort] | first // empty')" ||
      port=""
    if [ -n "$port" ]; then
      echo "-- $pod /readyz:"
      kubectl get --raw "/api/v1/namespaces/$NAMESPACE/pods/$pod:$port/proxy/readyz" 2>&1 | head -c 2000 || true
      echo
    fi
  done
}
# The highest value of a jq path in the events stream's details over the live NATS servers; the
# highest, because a follower may trail the leader by a moment. 0 when none answers.
nats_max() {  # nats_max <jq path within the stream detail> <node to leave out>
  local pod best=0 value
  for pod in $(ready_pods app.kubernetes.io/name=nats,app.kubernetes.io/component=nats "$2"); do
    value="$(kubectl -n "$NAMESPACE" exec --request-timeout=10s "$pod" -c nats -- \
      wget -qO- 'http://127.0.0.1:8222/jsz?accounts=true&streams=true&consumers=true' 2>/dev/null |
      jq -r --arg s "$EVENTS_STREAM" --arg c "$FANOUT_CONSUMER" \
        "[.account_details[]?.stream_detail[]? | select(.name == \$s) | $1] | max // 0")" || continue
    [[ "$value" =~ ^[0-9]+$ ]] && [ "$value" -gt "$best" ] && best="$value"
  done
  echo "$best"
}
# Who leads JetStream (its meta group), the events stream and the fan-out's consumer, as one live
# server sees it. A leader on the stopped node is replaced only once its peers notice the node is
# gone (NATS ping_interval x ping_max on the routes), which is what a slow fan-out waits on.
js_leaders() {  # js_leaders <node to leave out>
  local pod
  pod="$(ready_pods app.kubernetes.io/name=nats,app.kubernetes.io/component=nats "$1" | head -n 1)"
  [ -n "$pod" ] || { echo "JetStream leaders: no live NATS server answers"; return 0; }
  kubectl -n "$NAMESPACE" exec --request-timeout=10s "$pod" -c nats -- \
    wget -qO- 'http://127.0.0.1:8222/jsz?accounts=true&streams=true&consumers=true' 2>/dev/null |
    jq -r --arg s "$EVENTS_STREAM" --arg c "$FANOUT_CONSUMER" '
      "JetStream leaders (as \(.server_name // "?") sees them): meta \(.meta_cluster.leader // "none")"
      + ", \($s) \([.account_details[]?.stream_detail[]? | select(.name == $s) | .cluster.leader // "none"] | first // "none")"
      + ", \($c) \([.account_details[]?.stream_detail[]? | select(.name == $s) | .consumer_detail[]? | select(.name == $c) | .cluster.leader // "none"] | first // "none")"' ||
    echo "JetStream leaders: $pod did not answer"
}
# Acknowledged past <sequence>: the fan-out received and handled an event written after it.
fanout_acked_past() {  # fanout_acked_past <sequence> <node to leave out>
  # shellcheck disable=SC2016 # $c is jq's variable (nats_max passes it), not this shell's
  [ "$(nats_max '.consumer_detail[]? | select(.name == $c) | .ack_floor.stream_seq' "$2")" -gt "$1" ]
}
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
fanout_node="$(kubectl -n "$NAMESPACE" get pods -l "$FANOUT_LABELS" -o jsonpath='{.items[0].spec.nodeName}')"
js_leaders ""  # before the stop: which leaders the test is about to take away
echo "== stop $node (PostgreSQL primary $primary; also on it:" \
  "$(kubectl -n "$NAMESPACE" get pods --field-selector "spec.nodeName=$node" -o name | sed 's#pod/##' | tr '\n' ' '))"
STOPPED="$node"
k3d node stop "$node"

took="$(until_ok 300 promoted "$primary")" ||
  { echo "no standby promoted within 300 s"; exit 1; }
echo "promoted after ${took}s: $(pg '{.status.currentPrimary}')"
# The API's database sockets give up on a lost pooler copy in about 15 s (TCP_USER_TIMEOUT,
# app/core/database.py), so a request meets a live copy soon after (run 1 took 294 s before).
# 60 s (D-163): NodeLocal DNSCache (deploy/k3s/node-local-dns.sh) answers the sentinels'
# lookups from every node's own cache, so a lost node's CoreDNS copy no longer stalls them
# into TILT (a fixed 30 s pause). Before it, failover took about 50 s and this was 90 s
# (runs 43153098860 and 43157246881: 37-54 s).
WRITE_BUDGET=60
took="$(until_ok "$WRITE_BUDGET" save_locale '"ar"')" ||
  { echo "the session or the write did not come back within ${WRITE_BUDGET} s of the promotion (last answer: $(head -c 300 "$BODY"))"; show_write_trace; exit 1; }
echo "the same session writes again after ${took}s more"
show_write_trace

# Live updates (ADR-023): the fan-out runs one copy on purpose, so after a node loss it must come
# back by itself. On the stopped node it is evicted ha.fastEvictionSeconds (30 s) after the node
# goes NotReady, not after the default 300 s, and starts on a live node; until then screens get
# no live updates and reconcile when the realtime connection returns.
if [ "$fanout_node" = "$node" ]; then
  took="$(until_ok "$FANOUT_BUDGET" fanout_ready_off "$node")" ||
    { echo "the fan-out was on $node and no ready copy runs elsewhere within ${FANOUT_BUDGET} s"
      js_leaders "$node"
      kubectl -n "$NAMESPACE" get pods -l "$FANOUT_LABELS" -o wide
      fanout_diagnose "$node"
      exit 1; }
  echo "the fan-out moved off $node: ready on another node after ${took}s more"
  js_leaders "$node"
else
  echo "the fan-out was on ${fanout_node:-no node}, not on $node: it did not need to move"
fi
# Events flow again: a write after the move (identity_access.user.updated, a routed event) is
# acknowledged by the fan-out's durable consumer. Proves the whole path relay -> NATS -> fan-out,
# not only that a pod is ready.
mark="$(nats_max '.state.last_seq' "$node")"
[ "$mark" -gt 0 ] || { echo "cannot read the events stream from any live NATS server"; exit 1; }
save_locale '"en"' || { echo "the write after the fan-out check failed (last answer: $(head -c 300 "$BODY"))"; exit 1; }
took="$(until_ok "$FANOUT_BUDGET" fanout_acked_past "$mark" "$node")" ||
  { echo "the fan-out did not acknowledge an event past stream sequence $mark within ${FANOUT_BUDGET} s"
    js_leaders "$node"; fanout_diagnose "$node"; exit 1; }
echo "live updates flow: the fan-out acknowledged past sequence $mark after ${took}s"
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
write_after_return || { echo "the session did not write again within 30 s of the node's return (ingress ready first)"; exit 1; }
echo "node-loss test passed: one agent lost, the database failed over, the session kept writing"
