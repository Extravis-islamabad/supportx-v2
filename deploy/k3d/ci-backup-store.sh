#!/usr/bin/env bash
# CI's backup store (D-166): the k3d HA cluster's database backups go to an S3 store that is NOT
# on the cluster's nodes, as production's go to storage outside the cluster (docs/deployment.md,
# Backups). With the replicated SeaweedFS on every node, the node-loss test also degraded an
# in-cluster archive, and PostgreSQL's end-of-recovery WAL lookups stalled the promotion (Cluster
# run 43376122580). CI only: one SeaweedFS container (the chart's pinned image) beside the k3d
# nodes on the cluster's docker network, never stopped by a node-loss test.
#
#   ci-backup-store.sh up     start it (kept when it runs, restarted when stopped: re-creating it
#                             would wipe the archive and its SSE key), create the bucket and the
#                             release namespace's credentials Secret (never overwritten), and
#                             print the path of a values file for `helm upgrade -f` (no secret)
#   ci-backup-store.sh down   remove it and its data (`make cluster-down`, before the cluster)
#
# Encrypted at rest: SeaweedFS's SSE-S3 with a key of its own (generated here, inside the
# container only), so the chart's `encryption: AES256` is true here, as it must be off-cluster.
# Prints no secret. Pods reach it by its address on the k3d network (container names don't
# resolve inside pods); the egress allow-list gets that address on port 8333 only.
set -euo pipefail

CLUSTER="${K3D_CLUSTER:-supportx}"
NAMESPACE="${SUPPORTX_NAMESPACE:-supportx}"
STORE="k3d-${CLUSTER}-backups"
NETWORK="k3d-${CLUSTER}"
BUCKET="supportx-ci-backups"
SECRET="supportx-ci-backups-s3"      # postgresql.cnpg.backup.credentialsSecret's keys
CONF=/etc/supportx-ci-backups         # inside the container: s3.json and the key pair
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VALUES="${TMPDIR:-/tmp}/supportx-ci-backup-store.${CLUSTER}.yaml"

log() { echo "$*" >&2; }
running() { [ "$(docker inspect -f '{{.State.Running}}' "$STORE" 2>/dev/null)" = true ]; }
exists() { docker inspect "$STORE" >/dev/null 2>&1; }
store_ip() { docker inspect -f "{{(index .NetworkSettings.Networks \"$NETWORK\").IPAddress}}" "$STORE"; }
shell() { echo "$1" | docker exec -i "$STORE" weed shell 2>&1; }
s3_up() { [ "$(docker exec "$STORE" curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8333/)" != 000 ]; }

down() {
  if exists; then
    docker rm -f -v "$STORE" >/dev/null
    log "backup store $STORE removed"
  fi
}

start() {
  local image access secret
  # The chart's own pinned SeaweedFS image (values.yaml images.seaweedfs): nothing new pulled.
  image="$(sed -n 's/^  seaweedfs: *\([^ #]*\).*/\1/p' "$ROOT/deploy/helm/supportx/values.yaml" | head -n 1)"
  [ -n "$image" ] || { log "images.seaweedfs not found in values.yaml"; exit 1; }
  docker network inspect "$NETWORK" >/dev/null 2>&1 || { log "no docker network $NETWORK: make cluster-up-ha first"; exit 1; }
  # Credentials: the Secret's when it exists (a re-created store keeps them), else new ones.
  if kubectl -n "$NAMESPACE" get secret "$SECRET" >/dev/null 2>&1; then
    access="$(kubectl -n "$NAMESPACE" get secret "$SECRET" -o 'jsonpath={.data.ACCESS_KEY_ID}' | base64 -d)"
    secret="$(kubectl -n "$NAMESPACE" get secret "$SECRET" -o 'jsonpath={.data.ACCESS_SECRET_KEY}' | base64 -d)"
  else
    access="$(openssl rand -hex 12)"
    secret="$(openssl rand -hex 24)"
  fi
  # The host copy sits in a private folder; inside, the files must be readable by the image's
  # unprivileged seaweed user (its entrypoint drops root), and docker cp makes them root's.
  mkdir -m 0755 "$WORK/conf"
  printf '{"identities":[{"name":"ci-backups","credentials":[{"accessKey":"%s","secretKey":"%s"}],"actions":["Read","Write","List","Tagging"]}]}' \
    "$access" "$secret" >"$WORK/conf/s3.json"
  printf '%s' "$access" >"$WORK/conf/ACCESS_KEY_ID"
  printf '%s' "$secret" >"$WORK/conf/ACCESS_SECRET_KEY"
  # SSE-S3's key-encryption key: without one SeaweedFS refuses AES256 uploads (HTTP 500).
  printf '[s3.sse]\nkek = "%s"\n' "$(openssl rand -hex 32)" >"$WORK/conf/security.toml"
  chmod 0644 "$WORK"/conf/*
  docker rm -f -v "$STORE" >/dev/null 2>&1 || true
  # Files copied in before the start: no secret in its environment, arguments or a host mount.
  docker create --name "$STORE" --network "$NETWORK" --restart unless-stopped \
    --label "supportx.ci-backup-store=$CLUSTER" \
    "$image" server -s3 -s3.config="$CONF/s3.json" -dir=/data >/dev/null
  docker cp "$WORK/conf/." "$STORE:$CONF" >/dev/null
  docker cp "$WORK/conf/security.toml" "$STORE:/etc/seaweedfs/security.toml" >/dev/null
  rm -rf "$WORK/conf"
  docker start "$STORE" >/dev/null
  log "backup store $STORE started ($image, network $NETWORK)"
}

up() {
  local ip started previous
  if running; then
    :
  elif exists; then
    # Stopped (a docker restart, a runner reboot): its volume holds the archive and the SSE key,
    # so start the same container; `start` would remove it with its data (-v).
    docker start "$STORE" >/dev/null
    log "backup store $STORE was stopped: started again (archive and key kept)"
  else
    start
  fi
  started=$SECONDS
  until s3_up && shell "s3.bucket.list" >/dev/null; do
    [ $((SECONDS - started)) -lt 120 ] || { log "backup store not ready within 120s"; docker logs --tail 40 "$STORE" >&2; exit 1; }
    sleep 2
  done
  if shell "s3.bucket.list" | grep -qw "$BUCKET"; then
    log "bucket $BUCKET exists: kept"
  else
    shell "s3.bucket.create -name $BUCKET" | grep -q "created bucket" || { log "bucket $BUCKET not created"; exit 1; }
    log "bucket $BUCKET created"
  fi
  kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 || kubectl create namespace "$NAMESPACE" >/dev/null
  if kubectl -n "$NAMESPACE" get secret "$SECRET" >/dev/null 2>&1; then
    log "secret $NAMESPACE/$SECRET exists: left unchanged"
  else
    docker cp "$STORE:$CONF/ACCESS_KEY_ID" "$WORK/ACCESS_KEY_ID" >/dev/null
    docker cp "$STORE:$CONF/ACCESS_SECRET_KEY" "$WORK/ACCESS_SECRET_KEY" >/dev/null
    kubectl -n "$NAMESPACE" create secret generic "$SECRET" \
      --from-file="$WORK/ACCESS_KEY_ID" --from-file="$WORK/ACCESS_SECRET_KEY" >/dev/null
    rm -f "$WORK/ACCESS_KEY_ID" "$WORK/ACCESS_SECRET_KEY"
    log "secret $NAMESPACE/$SECRET created"
  fi
  ip="$(store_ip)"
  [ -n "$ip" ] || { log "backup store has no address on $NETWORK"; exit 1; }
  # A restarted store may come back on another address (lane C, #484). The egress allow-list is
  # a /32 and the backup endpoint names the address, so an installed release must be upgraded
  # with the new values file before its next backup or restore: say so loudly.
  previous="$(sed -n 's|^ *endpointURL: http://\([0-9.]*\):8333$|\1|p' "$VALUES" 2>/dev/null || true)"
  if [ -n "$previous" ] && [ "$previous" != "$ip" ]; then
    log "WARNING: backup store moved from $previous to $ip: run 'helm upgrade -f $VALUES' on the" \
      "release before its next backup (the egress allow-list and endpoint still name $previous)"
  fi
  # `database`: the database's pods only (CloudNativePG instances, the restore drill's restore
  # cluster's included, which reads through the same ObjectStore), never every pod (least privilege).
  cat >"$VALUES" <<EOF
# Written by deploy/k3d/ci-backup-store.sh (CI only, D-166): the backups outside the k3d nodes.
postgresql:
  cnpg:
    backup:
      endpointURL: http://$ip:8333
      destinationPath: s3://$BUCKET/postgres
      credentialsSecret: $SECRET
      encryption: AES256
networkPolicies:
  egress:
    database:
      - to: [{ipBlock: {cidr: $ip/32}}]
        ports: [{protocol: TCP, port: 8333}]
EOF
  log "backup store at http://$ip:8333 (s3://$BUCKET/postgres)"
  echo "$VALUES"
}

# Private scratch folder for the credential files on their way in and out; always removed.
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
umask 077

case "${1:-}" in
  up) up ;;
  down) down ;;
  *) echo "usage: $0 up|down" >&2; exit 2 ;;
esac
