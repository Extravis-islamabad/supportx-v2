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
# Audit anchor-signing key (WP-018, ADR-027): "<key id>:<base64 32-byte Ed25519 seed>".
signing_key() { printf 'k%s:%s' "$(date -u +%Y%m%d)" "$(openssl rand -base64 32)"; }
# Files key ring (WP-022, ADR-028): "<key id>:<base64 32 random bytes>". Back it up with the other
# secrets: losing it loses every stored file (docs/architecture/files.md).
files_keys() { printf 'k%s:%s' "$(date -u +%Y%m%d)" "$(openssl rand -base64 32)"; }
# SeaweedFS S3 identity (WP-018): the access key pair the app uses, as SeaweedFS's s3.json.
s3_config() {
  printf '{"identities":[{"name":"supportx","credentials":[{"accessKey":"%s","secretKey":"%s"}],"actions":["Admin","Read","Write","List","Tagging"]}]}' "$1" "$2"
}

kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 || kubectl create namespace "$NAMESPACE" >/dev/null

S3_ACCESS="$(rand 12)"
S3_SECRET="$(rand 24)"

if kubectl -n "$NAMESPACE" get secret "$APP_SECRET" >/dev/null 2>&1; then
  # Existing values are never changed. Keys added by later work packages are filled in once.
  add_missing() {
    if [ -z "$(kubectl -n "$NAMESPACE" get secret "$APP_SECRET" -o "jsonpath={.data.$1}")" ]; then
      kubectl -n "$NAMESPACE" patch secret "$APP_SECRET" --type merge \
        -p "{\"stringData\":{\"$1\":$(printf '%s' "$2" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')}}" >/dev/null
      echo "secret $NAMESPACE/$APP_SECRET: added $1"
    fi
  }
  if [ -z "$(kubectl -n "$NAMESPACE" get secret "$APP_SECRET" -o 'jsonpath={.data.s3-access-key}')" ]; then
    add_missing s3-access-key "$S3_ACCESS"
    add_missing s3-secret-key "$S3_SECRET"
    add_missing seaweedfs-s3-config "$(s3_config "$S3_ACCESS" "$S3_SECRET")"
  fi
  add_missing audit-signing-key "$(signing_key)"
  add_missing files-keys "$(files_keys)"
  add_missing keycloak-identity-secret "$(rand 24)"
  echo "secret $NAMESPACE/$APP_SECRET exists: existing values left unchanged"
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
    --from-literal=keycloak-identity-secret="$(rand 24)" \
    --from-literal=nats-password="$(rand 24)" \
    --from-literal=valkey-password="$(rand 24)" \
    --from-literal=s3-access-key="$S3_ACCESS" \
    --from-literal=s3-secret-key="$S3_SECRET" \
    --from-literal=seaweedfs-s3-config="$(s3_config "$S3_ACCESS" "$S3_SECRET")" \
    --from-literal=audit-signing-key="$(signing_key)" \
    --from-literal=files-keys="$(files_keys)" >/dev/null
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
