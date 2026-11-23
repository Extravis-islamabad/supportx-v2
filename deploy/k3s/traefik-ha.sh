#!/usr/bin/env bash
# HA install requirement (WP-014b, ADR-038): k3s's bundled Traefik runs at least two ready copies
# on different nodes. Every request into SupportX passes Traefik; with k3s's one copy, losing its
# node left every client without an answer until the 300 s eviction (node-loss test).
#
# Checks only, changes nothing: the copies come from deploy/k3s/traefik-ha.yaml, a HelmChartConfig
# in /var/lib/rancher/k3s/server/manifests/ (k3s re-applies it at every start). Applying it from
# here instead would overwrite a HelmChartConfig a customer keeps in that folder, which k3s would
# then put back at its next start. Waits for k3s's Helm job to roll the change out, then fails
# unless two ready copies run on two different nodes (the same test as cluster-dns-ha.sh).
# Used by `make cluster-up-ha` (k3d) and by on-prem HA installs on k3s (docs/deployment.md).
set -euo pipefail

NS=kube-system
COPIES=2
# The chart's own selector labels (traefik-40.1.0 traefik.labelselector).
SELECTOR="app.kubernetes.io/name=traefik,app.kubernetes.io/instance=traefik-kube-system"

# Ready copies that are not on their way out (an old ReplicaSet's pods may still terminate).
nodes() {
  kubectl -n "$NS" get pods -l "$SELECTOR" -o json | jq -r '.items[]
    | select(.metadata.deletionTimestamp == null)
    | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))
    | .spec.nodeName' | sort -u
}
# k3s's Helm job may still be upgrading Traefik to two copies: up to five minutes.
for _ in $(seq 1 150); do
  [ "$(nodes | wc -l | tr -d ' ')" -ge "$COPIES" ] && break
  sleep 2
done
found="$(nodes | tr '\n' ' ')"
if [ "$(nodes | wc -l | tr -d ' ')" -lt "$COPIES" ]; then
  echo "Traefik: ready copies are on fewer than $COPIES nodes (${found:-none}). Is" \
    "deploy/k3s/traefik-ha.yaml in /var/lib/rancher/k3s/server/manifests/?" >&2
  kubectl -n "$NS" get pods -l "$SELECTOR" -o wide >&2 || true
  exit 1
fi
echo "Traefik: $COPIES ready copies on different nodes: $found"
