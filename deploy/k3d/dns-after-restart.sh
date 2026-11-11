#!/usr/bin/env bash
# Cluster DNS survives a k3s server restart (WP-014b) on the four-node k3d HA cluster.
# At every start k3s rewrites its packaged manifests (server/manifests/coredns.yaml) and applies
# each one again, unconditionally. deploy/k3s/cluster-dns-ha.sh relies on that apply being a
# three-way merge that leaves alone what the manifest does not set (replicas, affinity). This
# test proves it on the pinned k3s:
#   1. CoreDNS: two ready copies on different nodes, required anti-affinity in the spec;
#   2. restart the server node (k3d node stop, then start), wait for the Kubernetes API, the
#      nodes and k3s's re-apply of coredns.yaml (its Addon's ApplyingManifest event);
#   3. the same holds: still two ready copies on different nodes, the anti-affinity still there.
#      If k3s reset either, it fails and says so: then cluster-dns-ha.sh needs another route.
# The server node is always started again (trap); the app's /api/v1/ready answers before the end,
# so the restore drill after it runs on a whole cluster. Needs: make cluster-up-ha deploy-ha.
set -euo pipefail

SERVER="${K3D_SERVER_NODE:-k3d-supportx-server-0}"
PUBLIC_URL="${SUPPORTX_PUBLIC_URL:-http://supportx.localhost:8080}"
STOPPED=""
cleanup() {
  if [ -n "$STOPPED" ]; then
    echo "starting $STOPPED again (cleanup)"
    k3d node start "$STOPPED" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

until_ok() {  # until_ok <seconds> <command...>: retry every 3 s; the seconds it took
  local limit="$1" started=$SECONDS
  shift
  while ! "$@" >/dev/null 2>&1; do
    [ $((SECONDS - started)) -ge "$limit" ] && return 1
    sleep 3
  done
  echo $((SECONDS - started))
}
dns_nodes() {  # the distinct nodes of ready, non-terminating CoreDNS pods
  kubectl -n kube-system get pods -l k8s-app=kube-dns -o json | jq -r '[.items[]
    | select(.metadata.deletionTimestamp == null)
    | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))
    | .spec.nodeName] | unique | length'
}
dns_two_nodes() { [ "$(dns_nodes)" -ge 2 ]; }
# The deployment still asks for two copies and the required hostname anti-affinity.
dns_spec() {
  kubectl -n kube-system get deploy/coredns -o json | jq -r '
    (.spec.replicas | tostring) + " " +
    ([.spec.template.spec.affinity.podAntiAffinity.requiredDuringSchedulingIgnoredDuringExecution[]?
      | select(.topologyKey == "kubernetes.io/hostname" and .labelSelector.matchLabels["k8s-app"] == "kube-dns")]
      | length | tostring)'
}
check_dns() {  # check_dns <when>
  local spec
  spec="$(dns_spec)"
  if [ "${spec% *}" -lt 2 ] || [ "${spec#* }" -lt 1 ]; then
    echo "$1: k3s reset CoreDNS: replicas ${spec% *}, hostname anti-affinity rules ${spec#* } (wanted 2 and 1)" >&2
    kubectl -n kube-system get deploy/coredns -o jsonpath='{.spec.template.spec.affinity}' >&2 || true
    echo >&2
    exit 1
  fi
  local took
  took="$(until_ok 180 dns_two_nodes)" || {
    echo "$1: CoreDNS is not ready on two nodes within 180 s" >&2
    kubectl -n kube-system get pods -l k8s-app=kube-dns -o wide >&2 || true
    exit 1
  }
  echo "$1: CoreDNS replicas ${spec% *}, anti-affinity kept, ready on $(dns_nodes) nodes (after ${took}s)"
}
applied_since() {  # a coredns ApplyingManifest event on its Addon at or after $1 (RFC 3339)
  kubectl -n kube-system get events -o json | jq -e --arg since "$1" '[.items[]
    | select(.involvedObject.kind == "Addon" and .involvedObject.name == "coredns"
             and .reason == "ApplyingManifest")
    | (.lastTimestamp // .eventTime // .series.lastObservedTime // "")
    | select(. >= $since)] | length > 0'
}
app_ready() { [ "$(curl -s -m 10 -o /dev/null -w '%{http_code}' "$PUBLIC_URL/api/v1/ready")" = 200 ]; }

check_dns "before the restart"

restarted="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "== restart the k3s server $SERVER"
STOPPED="$SERVER"
k3d node stop "$SERVER"
k3d node start "$SERVER"
STOPPED=""
took="$(until_ok 300 kubectl get --raw /readyz)" || { echo "the Kubernetes API did not come back within 300 s" >&2; exit 1; }
echo "the Kubernetes API is back after ${took}s"
kubectl wait --for=condition=Ready nodes --all --timeout=300s
if took="$(until_ok 120 applied_since "$restarted")"; then
  echo "k3s applied coredns.yaml again after the restart (${took}s)"
else
  # Not a failure by itself: the state below is what counts. Said, so a change in k3s shows.
  echo "no ApplyingManifest event for coredns.yaml since the restart within 120 s (k3s may have changed how it re-applies)"
fi

check_dns "after the restart"
took="$(until_ok 300 app_ready)" || { echo "the app's /api/v1/ready did not answer 200 within 300 s of the restart" >&2; exit 1; }
echo "the app is ready again (${took}s); cluster DNS test after a server restart passed"
