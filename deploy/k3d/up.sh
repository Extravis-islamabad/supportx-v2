#!/usr/bin/env bash
# make cluster-up: the local k3d cluster (D-003, k3s pinned in cluster.yaml) plus prerequisites.
# Keeps an existing cluster as it is; never deletes anything.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="supportx"

if k3d cluster list "$NAME" >/dev/null 2>&1; then
  echo "k3d cluster $NAME exists: kept"
  kubectl config use-context "k3d-$NAME" >/dev/null
else
  # K3D_CONFIG: cluster-ha.yaml for the HA smoke (four nodes), else the one-node cluster.
  k3d cluster create --config "$HERE/${K3D_CONFIG:-cluster.yaml}"
fi

# k3s installs Traefik (with our Gateway API settings) through Helm jobs after start-up.
echo "waiting for Traefik..."
for _ in $(seq 1 120); do
  kubectl -n kube-system get deploy traefik >/dev/null 2>&1 && break
  sleep 2
done
kubectl -n kube-system rollout status deploy/traefik --timeout=300s
bash "$HERE/prereqs.sh"

if [ "${HA_CLUSTER:-0}" = 1 ]; then
  # Before the chart: cluster DNS never single (two CoreDNS copies, never on one node). With
  # k3s's one copy, Cluster run 43082299609 lost every name lookup for about six minutes when
  # the node-loss test stopped its node, and Valkey could not fail over. The same script as an
  # on-prem HA install on k3s, then the same preflight, strict: any warning fails the bring-up.
  bash "$HERE/../k3s/cluster-dns-ha.sh"
  # Traefik the same: two ready copies on two nodes (cluster-ha.yaml installs
  # deploy/k3s/traefik-ha.yaml). With k3s's one copy, the node-loss test's stopped agent took the
  # only ingress with it and no request was answered for 90 s, the API pods healthy.
  bash "$HERE/../k3s/traefik-ha.sh"
  HA_PREFLIGHT_STRICT=1 bash "$HERE/../k3s/ha-preflight.sh"
fi
