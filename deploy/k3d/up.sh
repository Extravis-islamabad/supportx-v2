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
  k3d cluster create --config "$HERE/cluster.yaml"
fi

# k3s installs Traefik (with our Gateway API settings) through Helm jobs after start-up.
echo "waiting for Traefik..."
for _ in $(seq 1 120); do
  kubectl -n kube-system get deploy traefik >/dev/null 2>&1 && break
  sleep 2
done
kubectl -n kube-system rollout status deploy/traefik --timeout=300s
bash "$HERE/prereqs.sh"
