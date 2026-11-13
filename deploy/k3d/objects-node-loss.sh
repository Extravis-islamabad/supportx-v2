#!/usr/bin/env bash
# The object-storage node-loss test (D-166) on the four-node k3d cluster with values-ha.yaml,
# where SeaweedFS runs replicated (three masters, three volume servers, two filers, replication
# 001: two copies of every file on two nodes). Run after node-loss.sh, on a settled cluster:
#   1. sign in as a dev user through the BFF and upload 20 attachments through the SupportX API
#      (editor drafts, the uploader's own); wait until the malware scan has passed each one
#      (ClamAV runs in HA CI) and download each once, its sha256 recorded;
#   2. pick the agent to stop: one holding neither PostgreSQL's primary nor the Valkey master
#      (their failovers are node-loss.sh's and valkey-node-loss.sh's), with a volume server, and
#      whose loss cluster DNS survives. SeaweedFS's raft leadership is handed to the master on it
#      (cluster.raft.transferLeader), so the stopped node holds the master leader and a volume
#      server, never by chance;
#   3. stop it (k3d node stop), as a node that loses power;
#   4. within 60 s all 20 download again with the same sha256, and 5 new ones upload (every
#      request retried until then: the lost node's API, filer and ingress copies keep their
#      endpoints until Kubernetes marks it NotReady, about 20 s); the new ones then pass the scan
#      and download intact;
#   5. the node starts again; once its pods are back, volume.fix.replication runs in the leader
#      master (weed shell, under the cluster lock) until every volume has its copies again
#      (two with 001), and all 25 files still download intact.
# Whatever happens, the stopped node is started again (trap). Prints the timings and no secret.
# Needs: make cluster-up-ha deploy-ha.
set -euo pipefail

NAMESPACE="${SUPPORTX_NAMESPACE:-supportx}"
PUBLIC_URL="${SUPPORTX_PUBLIC_URL:-http://supportx.localhost:8080}"
PG_CLUSTER="${SUPPORTX_PG_CLUSTER:-supportx-pg}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
USER_NAME="tech@demo.test"
COOKIES="$(mktemp)"  # the session's Cookie header, mode 600
BODY="$(mktemp)"     # the last API answer
WORK="$(mktemp -d)"  # the files, their IDs and sums
STOPPED=""
FILES=20
NEW=5
BUDGET=60            # seconds from the stop: every old file read, every new one written
SCAN_BUDGET=180      # the malware scan of a batch of uploads
RUN="$(date +%s)-$$"
MASTERS="app.kubernetes.io/part-of=supportx,app.kubernetes.io/component=seaweedfs-master"
VOLUMES="app.kubernetes.io/part-of=supportx,app.kubernetes.io/component=seaweedfs-volume"
# shellcheck source=deploy/k3d/ha-lib.sh
. "$ROOT/deploy/k3d/ha-lib.sh"
cleanup() {
  rm -rf "$COOKIES" "$BODY" "$WORK" "$SETTLE_REASON"
  # Never leave a node stopped (a local cluster is reused, and the next steps need it).
  if [ -n "$STOPPED" ]; then
    echo "starting $STOPPED again (cleanup)"
    k3d node start "$STOPPED" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

pg() { kubectl -n "$NAMESPACE" get "clusters.postgresql.cnpg.io/$PG_CLUSTER" -o "jsonpath=$1"; }
three_ready() { [ "$(pg '{.status.readyInstances}')" = 3 ]; }
sha() { if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }
pods() { kubectl -n "$NAMESPACE" get pods -l "$1" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'; }

# --- SeaweedFS, from inside its master pods (no credentials needed, no port opened) ----------
master_status() {  # master_status <pod>: the master's /cluster/status JSON
  kubectl -n "$NAMESPACE" exec --request-timeout=10s "$1" -c master -- \
    curl -s -m 5 http://127.0.0.1:9333/cluster/status 2>/dev/null
}
leader() {  # leader [node to leave out]: the leader master's pod name, as a live master names it
  local pod name
  for pod in $(pods "$MASTERS"); do
    [ -n "${1:-}" ] && [ "$(node_of "$pod")" = "$1" ] && continue
    name="$(master_status "$pod" | jq -r '.Leader // empty' 2>/dev/null | cut -d. -f1)"
    [ -n "$name" ] && { echo "$name"; return 0; }
  done
  return 1
}
is_leader() { [ "$(leader "${2:-}" || true)" = "$1" ]; }
weed_shell() {  # weed_shell <master pod> <command lines...>: SeaweedFS's admin shell, in the pod
  printf '%s\n' "${@:2}" | kubectl -n "$NAMESPACE" exec -i --request-timeout=120s "$1" -c master -- \
    weed shell -master=127.0.0.1:9333 2>&1
}
# Copies of each volume (volume.list prints a line per copy, under its server): "<id> <copies>".
volume_copies() {  # volume_copies <master pod>
  weed_shell "$1" volume.list | awk '/^ *volume Id:/ { id = $2; sub(/^Id:/, "", id); sub(/,$/, "", id); n[id]++ }
    END { for (v in n) print v, n[v] }' | sort -n
}
all_copies() {  # all_copies <master pod>: every volume has $COPIES copies, and there are volumes
  local copies
  copies="$(volume_copies "$1")"
  [ -n "$copies" ] && ! echo "$copies" | awk -v want="$COPIES" '$2 != want { bad = 1 } END { exit !bad }'
}
# One pass adds a missing copy or removes a surplus one (a returned server's copies of volumes
# re-made meanwhile); new copies take a few seconds to register with the master.
fix_replication() {  # fix_replication <master pod>: re-make or trim copies, then check them
  weed_shell "$1" lock "volume.fix.replication -apply" unlock >/dev/null
  sleep 5
  all_copies "$1"
}

# --- Files through the SupportX API (app/modules/system/api/files.py) ------------------------
upload() {  # upload <n>: the file's ID into $WORK/<n>.id (one Idempotency-Key per file: a retry is the same upload)
  local status
  status="$(api POST "/files?owner_type=draft&owner_id=$ME&name=objects-$RUN-$1.txt" \
    -H "X-CSRF-Token: $CSRF" -H "Idempotency-Key: objects-node-loss-$RUN-$1" \
    -H 'Content-Type: text/plain' --data-binary "@$WORK/$1.txt")"
  [ "$status" = 201 ] || write_failed "POST /files ($1)" "$status" || return 1
  jq -r .id "$BODY" > "$WORK/$1.id"
}
make_file() {  # make_file <n>: about 16 kB of fresh text, its sha256 into $WORK/<n>.sum
  { echo "SupportX objects node-loss test, run $RUN, file $1"; openssl rand -hex 8192; } > "$WORK/$1.txt"
  sha "$WORK/$1.txt" > "$WORK/$1.sum"
}
scanned() {  # scanned <n>: the scan passed and the file opens; a blocked or failed scan stops the test
  local status state
  status="$(api GET "/files/$(cat "$WORK/$1.id")")"
  [ "$status" = 200 ] || return 1
  state="$(jq -r .state "$BODY")"
  case "$state" in
    infected|scan_failed|deleted) echo "file $1: $state, not clean: the test stops"; exit 1 ;;
  esac
  [ "$(jq -r .openable "$BODY")" = true ]
}
downloaded() {  # downloaded <n>: a fresh link, the bytes behind it, and the recorded sha256
  local status url
  status="$(api POST "/files/$(cat "$WORK/$1.id")/link" -H 'Content-Type: application/json' \
    -H "X-CSRF-Token: $CSRF" -d '{"disposition": "attachment"}')"
  [ "$status" = 200 ] || write_failed "POST /files/<id>/link ($1)" "$status" || return 1
  url="$(jq -r .url "$BODY")"
  status="$(curl -s -m 10 -o "$WORK/$1.got" -w '%{http_code}' -H "Cookie: $(cat "$COOKIES")" \
    -H 'X-SupportX-Client: console' "$PUBLIC_URL$url" || true)"
  [ "$status" = 200 ] || write_failed "GET file content ($1)" "$status" || return 1
  [ "$(sha "$WORK/$1.got")" = "$(cat "$WORK/$1.sum")" ] || write_failed "GET file content ($1)" "200, sha256 differs"
}
by_deadline() {  # by_deadline <deadline (SECONDS)> <command...>: retry every 2 s until it passes
  local deadline="$1"
  shift
  until "$@" 2>/dev/null; do
    [ "$SECONDS" -ge "$deadline" ] && return 1
    sleep 2
  done
}
all_scanned() {  # all_scanned <first> <last>: the whole batch within SCAN_BUDGET
  local n deadline=$((SECONDS + SCAN_BUDGET))
  for n in $(seq "$1" "$2"); do by_deadline "$deadline" scanned "$n" || return 1; done
}

echo "== sign in as $USER_NAME through the BFF; upload $FILES attachments"
sign_in "$USER_NAME"
status="$(api GET /auth/me)"
[ "$status" = 200 ] || { echo "GET /auth/me answered $status"; exit 1; }
ME="$(jq -r .user.id "$BODY")"
CSRF="$(jq -r .csrf_token "$BODY")"
started=$SECONDS
for n in $(seq 1 "$FILES"); do
  make_file "$n"
  upload "$n" || { echo "upload $n failed before any node was stopped"; show_write_trace; exit 1; }
done
all_scanned 1 "$FILES" || { echo "the $FILES uploads did not pass the malware scan within ${SCAN_BUDGET} s (last: $(head -c 300 "$BODY"))"; exit 1; }
for n in $(seq 1 "$FILES"); do
  downloaded "$n" || { echo "download $n failed before any node was stopped"; show_write_trace; exit 1; }
done
echo "$FILES files uploaded, scanned and downloaded intact in $((SECONDS - started)) s"

leader_pod="$(leader)" || { echo "no SeaweedFS master names a leader"; exit 1; }
REPLICATION="$(kubectl -n "$NAMESPACE" get pod "$leader_pod" -o json | jq -r '[.spec.containers[]
  | select(.name == "master") | .args[] | select(startswith("-defaultReplication="))
  | ltrimstr("-defaultReplication=")] | first // "000"')"
COPIES=$((1 + ${REPLICATION:2:1} + ${REPLICATION:1:1} + ${REPLICATION:0:1}))
[ "$COPIES" -ge 2 ] || { echo "SeaweedFS runs with replication $REPLICATION: one copy, nothing to test"; exit 1; }
until_ok 60 all_copies "$leader_pod" >/dev/null ||
  { echo "not every volume has $COPIES copies before the stop:"; volume_copies "$leader_pod"; exit 1; }
echo "replication $REPLICATION: every volume has $COPIES copies ($(volume_copies "$leader_pod" | wc -l | tr -d ' ') volumes)"

echo "== choose the node: the SeaweedFS leader and a volume server, not the database primary or the Valkey master"
# Settled first: the earlier tests' failovers may still be converging.
wait_settled 60 || exit 1
pg_node="$(node_of "$(pg '{.status.currentPrimary}')")"
valkey_node="$(node_of "$(master_of supportx-valkey-0)")"
target="" node=""
for pod in $(pods "$MASTERS"); do
  n="$(node_of "$pod")"
  case "$n" in *agent*) ;; *) continue ;; esac
  [ "$n" = "$pg_node" ] || [ "$n" = "$valkey_node" ] && continue
  [ -n "$(kubectl -n "$NAMESPACE" get pods -l "$VOLUMES" --field-selector "spec.nodeName=$n" -o name)" ] || continue
  dns_guard "$n" >/dev/null 2>&1 || continue
  target="$pod" node="$n"
  break
done
[ -n "$target" ] || { echo "no agent without the database primary ($pg_node) and the Valkey master ($valkey_node) holds a SeaweedFS master and a volume server"; exit 1; }
if [ "$leader_pod" != "$target" ]; then
  svc="${target%-*}"
  weed_shell "$leader_pod" "cluster.raft.transferLeader -id $target.$svc:9333 -address $target.$svc:19333" >/dev/null || true
  took="$(until_ok 60 is_leader "$target")" ||
    { echo "the raft leadership did not move from $leader_pod to $target (leader: $(leader || true))"; exit 1; }
  echo "raft leadership handed from $leader_pod to $target in ${took} s"
  leader_pod="$target"
fi
dns_guard "$node" || exit 1

echo "== stop $node (SeaweedFS leader $leader_pod; also on it:" \
  "$(kubectl -n "$NAMESPACE" get pods --field-selector "spec.nodeName=$node" -o name | sed 's#pod/##' | tr '\n' ' '))"
STOPPED="$node"
k3d node stop "$node"
stopped_at=$SECONDS
deadline=$((stopped_at + BUDGET))
for n in $(seq 1 "$FILES"); do
  by_deadline "$deadline" downloaded "$n" ||
    { echo "file $n did not download intact within ${BUDGET} s of the stop"; show_write_trace; exit 1; }
  echo "  file $n read at t+$((SECONDS - stopped_at))s"
done
read_after=$((SECONDS - stopped_at))
echo "all $FILES files downloaded intact ${read_after} s after the stop"
# by_deadline only stops retrying at the deadline; a file read on its first try after it still
# passes there, so the whole batch is held to the budget here (run 43320676209: 107 s passed).
[ "$read_after" -le "$BUDGET" ] ||
  { echo "the $FILES files took ${read_after} s to read after the stop, over the ${BUDGET} s budget"; show_write_trace; exit 1; }
for n in $(seq $((FILES + 1)) $((FILES + NEW))); do
  make_file "$n"
  by_deadline "$deadline" upload "$n" ||
    { echo "new file $n did not upload within ${BUDGET} s of the stop"; show_write_trace; exit 1; }
done
write_after=$((SECONDS - stopped_at))
echo "$NEW new files uploaded ${write_after} s after the stop"
[ "$write_after" -le "$BUDGET" ] ||
  { echo "the $NEW new files were written ${write_after} s after the stop, over the ${BUDGET} s budget"; show_write_trace; exit 1; }
show_write_trace
new_leader="$(leader "$node" || true)"
[ -n "$new_leader" ] && echo "SeaweedFS leader now: $new_leader (on $(node_of "$new_leader"))"
all_scanned $((FILES + 1)) $((FILES + NEW)) || { echo "the new files did not pass the malware scan with $node down"; exit 1; }
for n in $(seq $((FILES + 1)) $((FILES + NEW))); do
  until_ok 60 downloaded "$n" >/dev/null || { echo "new file $n did not download intact with $node down"; show_write_trace; exit 1; }
done
echo "the new files passed the scan and downloaded intact $((SECONDS - stopped_at)) s after the stop"

echo "== $node starts again"
k3d node start "$node"
STOPPED=""
kubectl wait --for=condition=Ready "node/$node" --timeout=300s
returned=$SECONDS
for selector in "$MASTERS" "$VOLUMES"; do
  kubectl -n "$NAMESPACE" wait --for=condition=Ready pod -l "$selector" --timeout=300s >/dev/null
done
leader_pod="$(until_ok 60 leader >/dev/null && leader)" || { echo "no SeaweedFS leader after the return"; exit 1; }
took="$(until_ok 180 fix_replication "$leader_pod")" ||
  { echo "volume.fix.replication did not bring every volume back to $COPIES copies within 180 s:"; volume_copies "$leader_pod"; exit 1; }
echo "every volume has $COPIES copies again ($(volume_copies "$leader_pod" | wc -l | tr -d ' ') volumes; fix.replication done ${took} s after the pods were ready)"
for n in $(seq 1 $((FILES + NEW))); do
  until_ok 30 downloaded "$n" >/dev/null || { echo "file $n did not download intact after the return"; show_write_trace; exit 1; }
done
echo "all $((FILES + NEW)) files download intact after the return"
write_after_return || { echo "the session did not write again within 30 s of the node's return (ingress ready first)"; exit 1; }

# Settled for the next steps (DNS restart, restore drill): the database and Sentinel whole again.
until_ok 600 three_ready >/dev/null ||
  { echo "the database did not get back to three ready instances: $(pg '{.status.phase}')"; exit 1; }
wait_settled 300 || exit 1
echo "timings: reads ${read_after} s and writes ${write_after} s after the stop (budget ${BUDGET} s); copies whole $((SECONDS - returned)) s after the node was Ready"
echo "object-storage node-loss test passed: the SeaweedFS leader's node lost, every file read and written, every volume back to $COPIES copies"
