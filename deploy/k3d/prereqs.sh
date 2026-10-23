#!/usr/bin/env bash
# Cluster-wide prerequisites of the supportx chart (D-037), installed once per cluster:
#   CloudNativePG operator (PostgreSQL, D1). Traefik and the Gateway API CRDs come with k3s.
# Idempotent: `helm upgrade --install` keeps an existing operator, at this pinned version.
set -euo pipefail

CNPG_CHART_VERSION="0.29.1"   # operator 1.30.1

helm repo add cnpg https://cloudnative-pg.github.io/charts --force-update >/dev/null
helm upgrade --install cnpg cnpg/cloudnative-pg --version "$CNPG_CHART_VERSION" \
  --namespace cnpg-system --create-namespace --wait --timeout 5m >/dev/null
echo "CloudNativePG operator ready (chart $CNPG_CHART_VERSION)"
kubectl get gatewayclass traefik >/dev/null 2>&1 \
  && echo "Gateway API: GatewayClass traefik present" \
  || { echo "GatewayClass traefik missing: is Traefik's Gateway provider on? (deploy/k3d/traefik-config.yaml)" >&2; exit 1; }
