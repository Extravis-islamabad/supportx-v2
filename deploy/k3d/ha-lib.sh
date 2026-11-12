# Shared by the HA cluster tests (node-loss.sh, valkey-node-loss.sh); sourced, never run. Each
# test sets NAMESPACE, PUBLIC_URL, ROOT, COOKIES (the session's Cookie header, mode 600) and BODY
# (the last API answer) first. Prints no secret: the Valkey password stays inside the pods
# (REDISCLI_AUTH from the container's own environment, as in ha-smoke.sh).
# shellcheck shell=bash

VALKEY_PODS="supportx-valkey-0 supportx-valkey-1 supportx-valkey-2"
SETTLE_REASON="$(mktemp)"  # why the last sentinel_settled said no

sign_in() {  # sign_in <user>: a session through the BFF (ha_login.py), its cookies in $COOKIES
  local realm="$ROOT/deploy/helm/supportx/files/keycloak/dev/supportx-realm.json"
  HA_LOGIN_PASSWORD="$(jq -r --arg u "$1" '.users[] | select(.username == $u) | .credentials[0].value' "$realm")" \
    uv run --project "$ROOT/backend" python "$ROOT/deploy/k3d/ha_login.py" "$PUBLIC_URL" "$1" "$COOKIES"
}
api() {  # api METHOD PATH [curl args...]: prints the status; the body goes to $BODY
  local method="$1" path="$2"
  shift 2
  curl -s -m 10 -X "$method" -o "$BODY" -w '%{http_code}' -H "Cookie: $(cat "$COOKIES")" \
    -H 'X-SupportX-Client: console' "$@" "$PUBLIC_URL/api/v1$path" || true  # -w already wrote 000
}
WRITE_TRACE="$(mktemp)"  # each failed write attempt: when, which step, its status and code
write_failed() {  # write_failed <step> <status>: one trace line (never a body's data)
  local code
  code="$(jq -r '.code // empty' "$BODY" 2>/dev/null | head -c 60)"
  echo "t+${SECONDS}s $1 -> $2${code:+ ($code)}" >> "$WRITE_TRACE"
  return 1
}
show_write_trace() {  # the attempts' story, each change once (a slow or failed write says why)
  [ -s "$WRITE_TRACE" ] || return 0
  echo "write attempts (step -> status, changes only):"
  awk '{key=$2" "$3" "$4" "$5} key!=last {print "  "$0; last=key}' "$WRITE_TRACE" | tail -n 30
  : > "$WRITE_TRACE"
}
save_locale() {  # save_locale <"ar" | null>: 0 once the API stored it
  local value="$1" status me_id csrf version
  status="$(api GET /auth/me)"
  [ "$status" = 200 ] || write_failed "GET /auth/me" "$status" || return 1
  me_id="$(jq -r .user.id "$BODY")"
  csrf="$(jq -r .csrf_token "$BODY")"
  status="$(api GET "/users/$me_id")"
  [ "$status" = 200 ] || write_failed "GET /users/<me>" "$status" || return 1
  version="$(jq -r .version "$BODY")"
  status="$(api PATCH "/users/$me_id" -H 'Content-Type: application/json' \
    -H "If-Match: \"$version\"" -H "X-CSRF-Token: $csrf" -d "{\"ui_locale\": $value}")"
  [ "$status" = 200 ] || write_failed "PATCH /users/<me>" "$status" || return 1
  [ "$(jq -c .ui_locale "$BODY")" = "$value" ] || write_failed "PATCH /users/<me>" "200, not stored"
}
until_ok() {  # until_ok <seconds> <command...>: retry every 3 s; the seconds it took
  local limit="$1" started=$SECONDS
  shift
  while ! "$@" 2>/dev/null; do
    [ $((SECONDS - started)) -ge "$limit" ] && return 1
    sleep 3
  done
  echo $((SECONDS - started))
}
node_of() { kubectl -n "$NAMESPACE" get pod "$1" -o jsonpath='{.spec.nodeName}'; }

# After a stopped node is back: the ingress copy on it is Ready again, and the session writes
# within 30 s. A node that just rejoined can drop a request or two before its kube-proxy rules
# and its Traefik copy are in sync (Cluster run 43232617611: the first write after the return
# got no answer while that node's Traefik was still 0/1). Where the drop happens: k3d's front
# load balancer (nginx in the serverlb container) sends to every node, health-checked or not;
# inside the cluster ServiceLB forwards each node's port to the Traefik Service and kube-proxy
# only picks ready copies. A real install's external load balancer must health-check each
# node's ingress port (docs/deployment.md, "Front load balancer"); the test allows the same
# settling window, bounded at 30 s, and prints what it took.
write_after_return() {  # write_after_return: 0 when the session writes again
  kubectl -n kube-system wait --for=condition=Ready pod -l app.kubernetes.io/name=traefik \
    --timeout=120s >/dev/null || return 1
  local took
  took="$(until_ok 30 save_locale null)" || return 1
  echo "the session wrote again ${took} s after the node's ingress was ready"
}

# valkey-cli inside a pod's container (valkey: port 6379, sentinel: 26379), bounded in time.
vcli() {  # vcli <pod> <valkey|sentinel> <args...>
  local pod="$1" container="$2" port=6379
  shift 2
  [ "$container" = sentinel ] && port=26379
  # shellcheck disable=SC2016 # expanded inside the container: the password never leaves it
  kubectl -n "$NAMESPACE" exec --request-timeout=10s "$pod" -c "$container" -- sh -c \
    'REDISCLI_AUTH="$VALKEY_PASSWORD" exec valkey-cli -p "$0" --no-auth-warning "$@"' "$port" "$@" \
    2>/dev/null | tr -d '\r'
}
# SENTINEL master / replicas print flat "key" / "value" lines; one field of the master, or one
# line per replica: "<ip> <flags>".
sentinel_field() {  # sentinel_field <pod> <field>
  vcli "$1" sentinel SENTINEL master supportx | awk -v k="$2" 'prev == k { print; exit } { prev = $0 }'
}
sentinel_replicas() {  # sentinel_replicas <pod>
  vcli "$1" sentinel SENTINEL replicas supportx | awk '
    function emit() { if (ip != "") print ip " " flags }
    prev == "name" { emit(); ip = ""; flags = "" }
    prev == "ip" { ip = $0 }
    prev == "flags" { flags = $0 }
    { prev = $0 }
    END { emit() }'
}
master_of() {  # master_of <pod>: the master's pod name, as that pod's sentinel names it
  vcli "$1" sentinel SENTINEL get-master-addr-by-name supportx | head -n 1 | cut -d. -f1
}
role_of() { vcli "$1" valkey info replication | sed -n 's/^role://p'; }

# Settled: every listed sentinel knows the other two sentinels, names the same master, healthy,
# and lists exactly two replicas, none down or disconnected. Before a node is stopped, Sentinel then
# has a quorum and a replica good enough to promote. Why it is not settled goes to $SETTLE_REASON.
sentinel_settled() {  # sentinel_settled [pods...] (default: all three)
  local pods="${*:-$VALKEY_PODS}" pod master="" this flags others replicas listed healthy
  for pod in $pods; do
    this="$(master_of "$pod")"
    flags="$(sentinel_field "$pod" flags)"
    others="$(sentinel_field "$pod" num-other-sentinels)"
    replicas="$(sentinel_replicas "$pod")"
    listed="$(echo "$replicas" | grep -c . || true)"
    healthy="$(echo "$replicas" | grep -v -e '^$' -e 's_down' -e 'o_down' -e 'disconnected' | grep -c . || true)"
    if [ -z "$this" ] || [ "$flags" != master ] || [ "$others" != 2 ] || [ "$listed" != 2 ] || [ "$healthy" != 2 ] ||
      { [ -n "$master" ] && [ "$this" != "$master" ]; }; then
      echo "$pod's sentinel: master ${this:-none} (flags ${flags:-none}), other sentinels ${others:-?}, replicas $listed ($healthy healthy): $(echo "$replicas" | tr '\n' ';')" > "$SETTLE_REASON"
      return 1
    fi
    master="$this"
  done
  echo "settled: master $master" > "$SETTLE_REASON"
}
wait_settled() {  # wait_settled <seconds> [pods...]: fails with the reason
  local limit="$1" took
  shift
  if took="$(until_ok "$limit" sentinel_settled "$@")"; then
    echo "Sentinel settled after ${took}s ($(cat "$SETTLE_REASON"))"
  else
    echo "Sentinel did not settle within ${limit}s: $(cat "$SETTLE_REASON")" >&2
    return 1
  fi
}

# Cluster DNS must outlive the node about to stop (Cluster run 43082299609): a node holding a
# CoreDNS copy may go only when another ready copy runs elsewhere (deploy/k3s/cluster-dns-ha.sh).
dns_guard() {  # dns_guard <node>
  local pods on_node ready
  pods="$(kubectl -n kube-system get pods -l k8s-app=kube-dns -o json | jq -r '.items[]
    | select(.metadata.deletionTimestamp == null)
    | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))
    | .spec.nodeName')"
  ready="$(echo "$pods" | grep -c . || true)"
  on_node="$(echo "$pods" | grep -cxF "$1" || true)"
  if [ "$on_node" -gt 0 ] && [ "$ready" -lt 2 ]; then
    echo "$1 holds a CoreDNS copy and only $ready ready copies run: stopping it would stop cluster DNS (run deploy/k3s/cluster-dns-ha.sh)" >&2
    kubectl -n kube-system get pods -l k8s-app=kube-dns -o wide >&2 || true
    return 1
  fi
  echo "cluster DNS: $ready ready copies; $on_node on $1"
}
