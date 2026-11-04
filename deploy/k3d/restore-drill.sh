#!/usr/bin/env bash
# The restore drill (WP-014b): backups are only real once one has been restored. On the k3d HA
# cluster, where values-ha-ci.yaml turns backups on:
#   1. write a "before" row and wait until WAL archiving works and a base backup is complete;
#   2. note the moment T, write an "after" row, and wait until its WAL is archived;
#   3. restore into a new cluster as of T, with the runbook's own manifest
#      (deploy/runbooks/restore-cluster.yaml, docs/runbooks/restore.md);
#   4. the restored database has "before" and not "after": point-in-time recovery works.
# The new cluster is removed afterwards. Needs: make cluster-up-ha deploy-ha. Prints no secret.
set -euo pipefail

NAMESPACE="${SUPPORTX_NAMESPACE:-supportx}"
SOURCE="${SUPPORTX_PG_CLUSTER:-supportx-pg}"
RESTORE="${SOURCE}-restore"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
k() { kubectl -n "$NAMESPACE" "$@"; }
pg() { k get "clusters.postgresql.cnpg.io/$1" -o "jsonpath=$2"; }
sql() {  # sql <pod> <statement>: one value back
  k exec "$1" -c postgres -- psql -U postgres -d postgres -tAc "$2" | tr -d '[:space:]'
}
until_true() {  # until_true <seconds> <what> <command...>
  local limit="$1" what="$2" started=$SECONDS
  shift 2
  until "$@" 2>/dev/null; do
    if [ $((SECONDS - started)) -ge "$limit" ]; then echo "$what: not within ${limit}s"; return 1; fi
    sleep 5
  done
  echo "$what after $((SECONDS - started))s"
}
cleanup() { k delete "clusters.postgresql.cnpg.io/$RESTORE" --ignore-not-found --wait=false >/dev/null 2>&1 || true; }
trap cleanup EXIT

primary="$(pg "$SOURCE" '{.status.currentPrimary}')"
echo "== $SOURCE (primary $primary): a row before the moment"
sql "$primary" "CREATE TABLE IF NOT EXISTS restore_drill (label text, at timestamptz DEFAULT now())" >/dev/null
sql "$primary" "TRUNCATE restore_drill" >/dev/null
sql "$primary" "INSERT INTO restore_drill (label) VALUES ('before')" >/dev/null
sql "$primary" "SELECT pg_switch_wal()" >/dev/null

archiving() { [ "$(pg "$SOURCE" '{.status.conditions[?(@.type=="ContinuousArchiving")].status}')" = True ]; }
backed_up() { k get backups.postgresql.cnpg.io -l "cnpg.io/cluster=$SOURCE" -o jsonpath='{.items[*].status.phase}' | grep -qw completed; }
until_true 600 "WAL archiving" archiving
until_true 900 "a completed base backup" backed_up

target="$(sql "$primary" "SELECT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US')")"
target="${target:0:10} ${target:10}+00"
sleep 2
sql "$primary" "INSERT INTO restore_drill (label) VALUES ('after')" >/dev/null
wal="$(sql "$primary" "SELECT pg_walfile_name(pg_switch_wal())")"
after_archived() {  # WAL file names sort in order within a timeline
  local last
  last="$(sql "$primary" "SELECT last_archived_wal FROM pg_stat_archiver")"
  [[ -n "$last" && ! "$last" < "$wal" ]]
}
until_true 300 "the after row's WAL archived" after_archived
echo "restoring to $target"

echo "== restore into $RESTORE (deploy/runbooks/restore-cluster.yaml)"
sed -e "s|RESTORE_NAME|$RESTORE|" -e "s|SOURCE_NAME|$SOURCE|" \
  -e "s|OBJECT_STORE|${SOURCE}-backups|" \
  -e "s|IMAGE|$(pg "$SOURCE" '{.spec.imageName}')|" \
  -e "s|STORAGE|1Gi|" -e "s|TARGET_TIME|$target|" \
  "$ROOT/deploy/runbooks/restore-cluster.yaml" | k apply -f - >/dev/null
k wait "clusters.postgresql.cnpg.io/$RESTORE" --for=condition=Ready --timeout=900s >/dev/null
echo "$RESTORE is ready"

rows="$(sql "${RESTORE}-1" "SELECT string_agg(label, ',' ORDER BY at) FROM restore_drill")"
echo "restored rows: $rows"
[ "$rows" = before ] || { echo "point-in-time recovery: expected only 'before', got '$rows'"; exit 1; }
echo "restore drill passed: a backup restored to a chosen moment, nothing after it"
