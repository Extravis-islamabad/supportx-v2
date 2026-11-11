#!/usr/bin/env bash
# HA preflight (WP-014b, ADR-038): checks the cluster a values-ha.yaml install goes on, before
# the install and after any cluster upgrade. Read-only: it changes nothing. Each unmet
# requirement prints a WARNING with how to fix it; the exit status is 0 unless HA_PREFLIGHT_STRICT=1
# (CI), when any warning fails it. Requirements (docs/deployment.md, Profiles):
#   - three or more Ready nodes that take workloads (copies never share a node);
#   - cluster DNS: at least two ready copies on different nodes. k3s ships one; when its node is
#     lost nothing resolves a name for about five minutes, and Valkey's sentinels, which find
#     each other by hostname, cannot fail over (Cluster run 43082299609). Fix on k3s:
#     deploy/k3s/cluster-dns-ha.sh;
#   - the CloudNativePG operator: two copies on different nodes (deploy/k3d/prereqs.sh shows how).
set -euo pipefail

warnings=0
warn() { echo "WARNING: $*"; warnings=$((warnings + 1)); }
# The distinct nodes of a namespace's ready pods with a label, pods on their way out left out.
ready_nodes() {  # ready_nodes <namespace> <label selector>
  kubectl -n "$1" get pods -l "$2" -o json | jq -r '.items[]
    | select(.metadata.deletionTimestamp == null)
    | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))
    | .spec.nodeName' | sort -u
}
count() { grep -c . || true; }

kubectl get nodes >/dev/null || { echo "ha-preflight: cannot reach the cluster" >&2; exit 2; }

nodes="$(kubectl get nodes -o json | jq -r '.items[]
  | select(any(.status.conditions[]; .type == "Ready" and .status == "True"))
  | select(.spec.unschedulable != true)
  | .metadata.name' | count)"
if [ "$nodes" -lt 3 ]; then
  warn "$nodes Ready schedulable nodes: the HA profile needs three or more"
else
  echo "ok: $nodes Ready schedulable nodes"
fi

dns="$(ready_nodes kube-system k8s-app=kube-dns | count)"
if [ "$dns" -lt 2 ]; then
  warn "cluster DNS (kube-system, k8s-app=kube-dns) has ready copies on $dns node(s): losing" \
    "that node stops every name lookup, and Valkey cannot fail over. Run two copies on different" \
    "nodes: on k3s, deploy/k3s/cluster-dns-ha.sh; elsewhere, scale your DNS deployment to 2 with" \
    "required pod anti-affinity on kubernetes.io/hostname"
else
  echo "ok: cluster DNS ready on $dns nodes"
fi

cnpg="$(ready_nodes cnpg-system app.kubernetes.io/name=cloudnative-pg | count)"
if [ "$cnpg" -lt 2 ]; then
  warn "the CloudNativePG operator has ready copies on $cnpg node(s): losing that node stops" \
    "database failover until the pod moves, about five minutes. Install it with replicaCount=2" \
    "and a hostname spread (deploy/k3d/prereqs.sh)"
else
  echo "ok: CloudNativePG operator ready on $cnpg nodes"
fi

if [ "$warnings" -gt 0 ]; then
  echo "ha-preflight: $warnings warning(s)"
  [ "${HA_PREFLIGHT_STRICT:-0}" = 1 ] && exit 1
else
  echo "ha-preflight: every check passed"
fi
exit 0
