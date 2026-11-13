#!/usr/bin/env bash
# The restore drill (WP-014b): backups are only real once one has been restored. On the k3d HA
# cluster, where values-ha-ci.yaml turns backups on:
#   1. write a "before" row and wait until WAL archiving works and a base backup is complete;
#   2. note the moment T, write an "after" row, and wait until its WAL is archived;
#   3. restore into a new cluster as of T, with the runbook's own manifest
#      (deploy/runbooks/restore-cluster.yaml, docs/runbooks/restore.md);
#   4. the restored database has "before" and not "after": point-in-time recovery works;
#   5. with HA SeaweedFS (D-166), its filers' metadata database is in the same cluster, so in the
#      same backups: the restored cluster has it, with the file entries it had before the moment.
# The backups are read through the release's own ObjectStore, so from wherever it points: with
# `make deploy-ha` the store outside the k3d nodes (deploy/k3d/ci-backup-store.sh), reached under
# the egress rule that values file adds for every pod of the namespace, the restore cluster's too.
# The new cluster is removed afterwards. Needs: make cluster-up-ha deploy-ha. Prints no secret.
set -euo pipefail

NAMESPACE="${SUPPORTX_NAMESPACE:-supportx}"
SOURCE="${SUPPORTX_PG_CLUSTER:-supportx-pg}"
RESTORE="${SOURCE}-restore"
FILER_DB="${SUPPORTX_FILER_DB:-seaweedfs_filer}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
k() { kubectl -n "$NAMESPACE" "$@"; }
pg() { k get "clusters.postgresql.cnpg.io/$1" -o "jsonpath=$2"; }
sql() {  # sql <pod> <statement> [database]: one value back
  k exec "$1" -c postgres -- psql -U postgres -d "${3:-postgres}" -tAc "$2" | tr -d '[:space:]'
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
report() {  # what the restore cluster was doing, before it goes (a failed drill only)
  echo "--- $RESTORE: status"
  k get "clusters.postgresql.cnpg.io/$RESTORE" -o jsonpath='{.status.phase}{"\n"}{.status.phaseReason}{"\n"}{range .status.conditions[*]}{.type}={.status} {.reason}: {.message}{"\n"}{end}' || true
  echo "--- $RESTORE: pods"
  k get pods -l "cnpg.io/cluster=$RESTORE" -o wide || true
  echo "--- $RESTORE-1: last log lines"
  k logs "${RESTORE}-1" -c postgres --tail=40 2>/dev/null || true
}
cleanup() {
  local status=$?
  [ "$status" = 0 ] || report
  k delete "clusters.postgresql.cnpg.io/$RESTORE" --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap cleanup EXIT

primary="$(pg "$SOURCE" '{.status.currentPrimary}')"
echo "== $SOURCE (primary $primary): a row before the moment"
sql "$primary" "CREATE TABLE IF NOT EXISTS restore_drill (label text, at timestamptz DEFAULT now())" >/dev/null
sql "$primary" "TRUNCATE restore_drill" >/dev/null
sql "$primary" "INSERT INTO restore_drill (label) VALUES ('before')" >/dev/null
sql "$primary" "SELECT pg_switch_wal()" >/dev/null
filer_entries=""
if [ "$(sql "$primary" "SELECT count(*) FROM pg_database WHERE datname = '$FILER_DB'")" = 1 ]; then
  filer_entries="$(sql "$primary" "SELECT count(*) FROM filemeta" "$FILER_DB")"
  echo "SeaweedFS filer metadata ($FILER_DB): $filer_entries entries"
  [ "$filer_entries" -gt 0 ] || { echo "$FILER_DB has no file entries: nothing to prove"; exit 1; }
fi

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
# Each phase it goes through, until it is healthy (or 15 minutes pass).
phase="" started=$SECONDS
while :; do
  now="$(pg "$RESTORE" '{.status.phase}' 2>/dev/null || true)"
  if [ "$now" != "$phase" ]; then echo "  $((SECONDS - started))s: ${now:-pending}"; phase="$now"; fi
  [ "$now" = "Cluster in healthy state" ] && break
  [ $((SECONDS - started)) -ge 900 ] && { echo "$RESTORE: not healthy within 900s"; exit 1; }
  sleep 5
done
echo "$RESTORE is ready"

rows="$(sql "${RESTORE}-1" "SELECT string_agg(label, ',' ORDER BY at) FROM restore_drill")"
echo "restored rows: $rows"
[ "$rows" = before ] || { echo "point-in-time recovery: expected only 'before', got '$rows'"; exit 1; }
if [ -n "$filer_entries" ]; then
  restored="$(sql "${RESTORE}-1" "SELECT count(*) FROM filemeta" "$FILER_DB" || true)"
  echo "restored SeaweedFS filer metadata ($FILER_DB): ${restored:-none} entries"
  # At least what it held before the chosen moment (counted before it was chosen): the filers
  # only add entries meanwhile (WAL archives), so fewer means entries were lost (lane C).
  if [ -z "$restored" ] || [ "$restored" -lt "$filer_entries" ]; then
    echo "the filers' metadata database $FILER_DB was not restored with its entries" \
      "(${restored:-none} restored, $filer_entries before the moment)"; exit 1
  fi
fi
echo "restore drill passed: a backup restored to a chosen moment, nothing after it"
