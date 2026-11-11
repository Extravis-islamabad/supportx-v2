#!/usr/bin/env bash
# HA install requirement (WP-014b, ADR-038): cluster DNS runs at least two copies, on different
# nodes. k3s ships ONE CoreDNS copy. In Cluster run 43082299609 the node-loss test stopped the
# agent that held it: nothing in the cluster resolved a name until Kubernetes re-created the pod
# after the 300 s unreachable eviction, Valkey's sentinels (which find each other by hostname)
# kept entering TILT, no quorum formed, and Valkey never failed over.
#
# This script makes k3s's CoreDNS highly available, idempotently:
#   1. two copies (kubectl scale);
#   2. REQUIRED pod anti-affinity on kubernetes.io/hostname, so the copies never share a node;
#   3. waits for the rollout and fails unless two ready copies run on two different nodes.
# k3s re-applies its packaged CoreDNS manifest at server start; that manifest sets neither
# replicas nor affinity, so a restart keeps both. An upgrade may ship a different manifest: run
# this again after every k3s upgrade, and deploy/k3s/ha-preflight.sh warns if DNS is single again.
# CoreDNS is a plain manifest in k3s, not a Helm chart, so a HelmChartConfig does not apply.
# Used by `make cluster-up-ha` (k3d) and by on-prem HA installs on k3s (docs/deployment.md).
set -euo pipefail

NS=kube-system
DEPLOY="${CLUSTER_DNS_DEPLOYMENT:-coredns}"
COPIES=2

kubectl -n "$NS" get "deploy/$DEPLOY" >/dev/null ||
  { echo "cluster DNS: no deployment $NS/$DEPLOY (set CLUSTER_DNS_DEPLOYMENT)" >&2; exit 1; }
kubectl -n "$NS" scale "deploy/$DEPLOY" --replicas="$COPIES"
kubectl -n "$NS" patch "deploy/$DEPLOY" --type=strategic -p '{"spec":{"template":{"spec":{"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"k8s-app":"kube-dns"}},"topologyKey":"kubernetes.io/hostname"}]}}}}}}'
kubectl -n "$NS" rollout status "deploy/$DEPLOY" --timeout=300s

# Ready copies that are not on their way out (an old ReplicaSet's pods may still terminate).
nodes() {
  kubectl -n "$NS" get pods -l k8s-app=kube-dns -o json | jq -r '.items[]
    | select(.metadata.deletionTimestamp == null)
    | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))
    | .spec.nodeName' | sort -u
}
for _ in $(seq 1 30); do
  [ "$(nodes | wc -l | tr -d ' ')" -ge "$COPIES" ] && break
  sleep 2
done
found="$(nodes | tr '\n' ' ')"
if [ "$(nodes | wc -l | tr -d ' ')" -lt "$COPIES" ]; then
  echo "cluster DNS: ready copies are on fewer than $COPIES nodes (${found:-none}):" >&2
  kubectl -n "$NS" get pods -l k8s-app=kube-dns -o wide >&2 || true
  exit 1
fi
echo "cluster DNS: $COPIES ready copies on different nodes: $found"
