#!/usr/bin/env bash
# NodeLocal DNSCache on a SupportX HA cluster (D-163; why: deploy/k3s/node-local-dns.yaml).
# Run after deploy/k3s/cluster-dns-ha.sh, once per cluster and after every k3s upgrade; it is
# idempotent. It renders the manifest with this cluster's kube-dns address, applies it, and fails
# unless a ready cache runs on every schedulable node and answers a lookup.
# Needs kube-proxy in iptables mode (k3s's default): in ipvs mode the kube-dns address is bound
# by kube-proxy itself and transparent mode cannot take it (ha-preflight.sh checks).
# The image comes from deploy/helm/supportx/values.yaml (images.nodeLocalDns), so the
# air-gapped mirror and this script use the same pin; IMAGE_REGISTRY points it at the mirror.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
NS=kube-system
LOCAL_IP="${NODE_LOCAL_DNS_IP:-169.254.20.10}"
VALUES="$HERE/../helm/supportx/values.yaml"

# An image from values.yaml's images block, moved to IMAGE_REGISTRY when set. Only a first path
# part that names a registry host (it has a dot or a port) is replaced: valkey/valkey keeps it.
pinned() {  # pinned <images key>
  local ref first
  ref="$(awk -v key="$1:" '$1 == "images:" {inside = 1; next}
    inside && /^[^ #]/ {exit}
    inside && $1 == key {print $2; exit}' "$VALUES")"
  [ -n "$ref" ] || { echo "node-local-dns: no images.$1 in $VALUES" >&2; return 1; }
  if [ -n "${IMAGE_REGISTRY:-}" ]; then
    first="${ref%%/*}"
    case "$first" in *.* | *:*) ref="${ref#*/}" ;; esac
    ref="$IMAGE_REGISTRY/$ref"
  fi
  echo "$ref"
}
image="$(pinned nodeLocalDns)"
dns_ip="$(kubectl -n "$NS" get svc kube-dns -o jsonpath='{.spec.clusterIP}')"
[ -n "$dns_ip" ] || { echo "node-local-dns: the kube-dns Service has no address" >&2; exit 1; }

sed -e "s|__LOCAL_IP__|$LOCAL_IP|g" -e "s|__DNS_IP__|$dns_ip|g" -e "s|__IMAGE__|$image|g" \
  "$HERE/node-local-dns.yaml" | kubectl apply -f -
kubectl -n "$NS" rollout status ds/node-local-dns --timeout=300s

want="$(kubectl get nodes -o json | jq '[.items[] | select(.spec.unschedulable != true)] | length')"
ready="$(kubectl -n "$NS" get ds node-local-dns -o jsonpath='{.status.numberReady}')"
if [ "${ready:-0}" -lt "$want" ]; then
  echo "node-local-dns: ready on $ready of $want schedulable nodes" >&2
  kubectl -n "$NS" get pods -l k8s-app=node-local-dns -o wide >&2 || true
  exit 1
fi

# A pod's lookup now goes through its node's cache: resolve a cluster name from a throwaway pod.
# The cache image has no shell; Valkey's image (already pinned and mirrored) has getent.
probe_image="$(pinned valkey)"
if ! kubectl -n "$NS" run "node-local-dns-probe-$RANDOM" --rm -i --restart=Never --quiet \
  --image="$probe_image" --command -- getent hosts kubernetes.default.svc.cluster.local; then
  echo "node-local-dns: a pod could not resolve kubernetes.default through the cache" >&2
  exit 1
fi
echo "node-local-dns: a ready cache on each of $want nodes (local $LOCAL_IP, kube-dns $dns_ip, $image)"
