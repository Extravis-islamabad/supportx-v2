#!/usr/bin/env bash
# Cluster-wide prerequisites of the supportx chart (D-037), installed once per cluster:
#   CloudNativePG operator (PostgreSQL, D1). Traefik and the Gateway API CRDs come with k3s.
#   With BACKUP_PLUGIN=1 (WP-014b backups): cert-manager and CloudNativePG's Barman Cloud plugin
#   (both Apache-2.0), which archives WAL and takes base backups to S3-compatible storage.
# Idempotent: `helm upgrade --install` keeps an existing operator, at this pinned version.
set -euo pipefail

CNPG_CHART_VERSION="0.29.1"   # operator 1.30.1
# The HA cluster runs two operator copies on different nodes (leader election): with one copy,
# losing its node also stops failover until Kubernetes moves the pod, about five minutes later.
CNPG_OPERATOR_REPLICAS="${CNPG_OPERATOR_REPLICAS:-1}"
BACKUP_PLUGIN="${BACKUP_PLUGIN:-0}"
CERT_MANAGER_CHART_VERSION="v1.21.3"
BARMAN_CHART_VERSION="0.8.1"   # plugin v0.15.1; both images pinned by digest below
BARMAN_IMAGE_TAG="v0.15.1@sha256:c75acad19a36e8176cfe2885761ff1b836c6ef977d7257e298c99a28b5c302ef"
BARMAN_SIDECAR_TAG="v0.15.1@sha256:2287a793a804db751edd0d07d44cd549e357677e98a800eb12e2cf7c0d53f9b0"

helm repo add cnpg https://cloudnative-pg.github.io/charts --force-update >/dev/null
helm upgrade --install cnpg cnpg/cloudnative-pg --version "$CNPG_CHART_VERSION" \
  --namespace cnpg-system --create-namespace --wait --timeout 5m \
  --set replicaCount="$CNPG_OPERATOR_REPLICAS" \
  --set-json 'topologySpreadConstraints=[{"maxSkew":1,"topologyKey":"kubernetes.io/hostname","whenUnsatisfiable":"DoNotSchedule","labelSelector":{"matchLabels":{"app.kubernetes.io/name":"cloudnative-pg"}}}]' \
  >/dev/null
echo "CloudNativePG operator ready (chart $CNPG_CHART_VERSION, $CNPG_OPERATOR_REPLICAS copies)"
if [ "$BACKUP_PLUGIN" = 1 ]; then
  # The plugin's webhook and gRPC certificates come from cert-manager.
  helm repo add jetstack https://charts.jetstack.io --force-update >/dev/null
  helm upgrade --install cert-manager jetstack/cert-manager --version "$CERT_MANAGER_CHART_VERSION" \
    --namespace cert-manager --create-namespace --wait --timeout 5m --set crds.enabled=true >/dev/null
  echo "cert-manager ready (chart $CERT_MANAGER_CHART_VERSION)"
  helm upgrade --install barman-cloud cnpg/plugin-barman-cloud --version "$BARMAN_CHART_VERSION" \
    --namespace cnpg-system --wait --timeout 5m \
    --set image.tag="$BARMAN_IMAGE_TAG" --set sidecarImage.tag="$BARMAN_SIDECAR_TAG" >/dev/null
  echo "Barman Cloud plugin ready (chart $BARMAN_CHART_VERSION)"
fi
kubectl get gatewayclass traefik >/dev/null 2>&1 \
  && echo "Gateway API: GatewayClass traefik present" \
  || { echo "GatewayClass traefik missing: is Traefik's Gateway provider on? (deploy/k3d/traefik-config.yaml)" >&2; exit 1; }
