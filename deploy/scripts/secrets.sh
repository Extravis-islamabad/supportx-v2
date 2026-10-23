#!/usr/bin/env bash
# Create the Kubernetes Secrets the supportx chart expects, with fresh random values (WP-014).
#
#   deploy/scripts/secrets.sh [namespace]      (default namespace: supportx)
#
# Never overwrites: an existing Secret is left exactly as it is, because its passwords are already
# inside the databases (CLAUDE.md rule h). Values are hex, so they are safe inside URLs. Nothing is
# printed or written to disk. Used by `make deploy-dev`, CI and, until the installer exists
# (WP-014c), single-node evaluation installs.
set -euo pipefail

NAMESPACE="${1:-supportx}"
APP_SECRET="supportx-app"
KEYCLOAK_DB_SECRET="supportx-db-keycloak"

rand() { openssl rand -hex "${1:-32}"; }

kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 || kubectl create namespace "$NAMESPACE" >/dev/null

if kubectl -n "$NAMESPACE" get secret "$APP_SECRET" >/dev/null 2>&1; then
  echo "secret $NAMESPACE/$APP_SECRET exists: left unchanged"
else
  kubectl -n "$NAMESPACE" create secret generic "$APP_SECRET" \
    --from-literal=app-db-password="$(rand 24)" \
    --from-literal=migrator-db-password="$(rand 24)" \
    --from-literal=relay-db-password="$(rand 24)" \
    --from-literal=session-secret="$(rand 32)" \
    --from-literal=centrifugo-token-secret="$(rand 32)" \
    --from-literal=centrifugo-api-key="$(rand 24)" \
    --from-literal=oidc-console-secret="$(rand 24)" \
    --from-literal=oidc-portal-secret="$(rand 24)" \
    --from-literal=keycloak-admin-password="$(rand 16)" \
    --from-literal=nats-password="$(rand 24)" \
    --from-literal=valkey-password="$(rand 24)" >/dev/null
  echo "secret $NAMESPACE/$APP_SECRET created"
fi

if kubectl -n "$NAMESPACE" get secret "$KEYCLOAK_DB_SECRET" >/dev/null 2>&1; then
  echo "secret $NAMESPACE/$KEYCLOAK_DB_SECRET exists: left unchanged"
else
  kubectl -n "$NAMESPACE" create secret generic "$KEYCLOAK_DB_SECRET" \
    --type=kubernetes.io/basic-auth \
    --from-literal=username=keycloak \
    --from-literal=password="$(rand 24)" >/dev/null
  echo "secret $NAMESPACE/$KEYCLOAK_DB_SECRET created"
fi
