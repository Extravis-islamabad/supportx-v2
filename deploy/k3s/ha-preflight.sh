#!/usr/bin/env bash
# HA preflight (WP-014b, ADR-038): checks the cluster a values-ha.yaml install goes on, before
# the install and after any cluster upgrade. Read-only: it changes nothing. Each unmet
# requirement prints a WARNING with how to fix it; the exit status is 0 unless HA_PREFLIGHT_STRICT=1
# (CI), when any warning fails it. Requirements (docs/deployment.md, Profiles):
#   - three or more Ready nodes that take workloads (copies never share a node);
#   - cluster DNS: at least two ready copies on different nodes. k3s ships one; when its node is
#     lost nothing resolves a name for about five minutes, and Valkey's sentinels, which find
#     each other by hostname, cannot fail over (Cluster run 43082299609). Fix on k3s:
#     deploy/k3s/cluster-dns-ha.sh;
#   - the CloudNativePG operator: two copies on different nodes (deploy/k3d/prereqs.sh shows how);
#   - k3s's bundled Traefik: two ready copies on different nodes (deploy/k3s/traefik-ha.yaml).
# Once SupportX is installed in SUPPORTX_NAMESPACE (default supportx, as `make deploy-ha` and the
# Cluster workflow use), it also checks the release itself:
#   - NATS servers on distinct nodes (values-ha.yaml's required anti-affinity);
#   - PostgreSQL instances on distinct nodes (CloudNativePG, required anti-affinity);
#   - the fast-eviction tolerations on the single-copy fan-out and index workers
#     (ha.fastEvictionSeconds);
#   - advisory, never failing even when strict: the bundled SeaweedFS is a single copy, not HA
#     (decision b, 2026-11-12: HA installs use their own S3-compatible store). CI's k3d HA cluster
#     runs it on purpose, so it must not fail the strict bring-up.
# Before the install (`make cluster-up-ha` runs this ahead of the chart) the release checks are
# skipped, not failed.
set -euo pipefail

NAMESPACE="${SUPPORTX_NAMESPACE:-supportx}"
warnings=0
advisories=0
warn() { echo "WARNING: $*"; warnings=$((warnings + 1)); }
advise() { echo "WARNING (advisory): $*"; advisories=$((advisories + 1)); }
# Nodes of a namespace's scheduled pods with a label, one line per pod (repeats show sharing).
pod_nodes() {  # pod_nodes <namespace> <label selector>
  kubectl -n "$1" get pods -l "$2" -o json | jq -r '.items[]
    | select(.metadata.deletionTimestamp == null)
    | select(.spec.nodeName != null)
    | .spec.nodeName'
}
# Pods (of a namespace, with a label) missing a NoExecute toleration below 300 s for both lost-node
# taints. Kubernetes adds 300 s tolerations to every pod that has none of its own.
slow_eviction_pods() {  # slow_eviction_pods <namespace> <label selector>
  kubectl -n "$1" get pods -l "$2" -o json | jq -r '.items[]
    | select(.metadata.deletionTimestamp == null)
    | select([.spec.tolerations[]?
        | select(.effect == "NoExecute" and (.tolerationSeconds // 300) < 300)
        | .key] as $k
        | ($k | index("node.kubernetes.io/unreachable")) == null
          or ($k | index("node.kubernetes.io/not-ready")) == null)
    | .metadata.name'
}
# The distinct nodes of a namespace's ready pods with a label, pods on their way out left out.
ready_nodes() {  # ready_nodes <namespace> <label selector>
  kubectl -n "$1" get pods -l "$2" -o json | jq -r '.items[]
    | select(.metadata.deletionTimestamp == null)
    | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))
    | .spec.nodeName' | sort -u
}
count() { grep -c . || true; }

kubectl get nodes >/dev/null || { echo "ha-preflight: cannot reach the cluster" >&2; exit 2; }

nodes="$(kubectl get nodes -o json | jq -r '.items[]
  | select(any(.status.conditions[]; .type == "Ready" and .status == "True"))
  | select(.spec.unschedulable != true)
  | .metadata.name' | count)"
if [ "$nodes" -lt 3 ]; then
  warn "$nodes Ready schedulable nodes: the HA profile needs three or more"
else
  echo "ok: $nodes Ready schedulable nodes"
fi

dns="$(ready_nodes kube-system k8s-app=kube-dns | count)"
if [ "$dns" -lt 2 ]; then
  warn "cluster DNS (kube-system, k8s-app=kube-dns) has ready copies on $dns node(s): losing" \
    "that node stops every name lookup, and Valkey cannot fail over. Run two copies on different" \
    "nodes: on k3s, deploy/k3s/cluster-dns-ha.sh; elsewhere, scale your DNS deployment to 2 with" \
    "required pod anti-affinity on kubernetes.io/hostname"
else
  echo "ok: cluster DNS ready on $dns nodes"
fi

cnpg="$(ready_nodes cnpg-system app.kubernetes.io/name=cloudnative-pg | count)"
if [ "$cnpg" -lt 2 ]; then
  warn "the CloudNativePG operator has ready copies on $cnpg node(s): losing that node stops" \
    "database failover until the pod moves, about five minutes. Install it with replicaCount=2" \
    "and a hostname spread (deploy/k3d/prereqs.sh)"
else
  echo "ok: CloudNativePG operator ready on $cnpg nodes"
fi

traefik="$(ready_nodes kube-system app.kubernetes.io/name=traefik | count)"
if [ "$traefik" -lt 2 ]; then
  warn "Traefik (kube-system) has ready copies on $traefik node(s): every request into SupportX" \
    "passes it, so losing that node leaves every client unanswered for about five minutes. On k3s" \
    "copy deploy/k3s/traefik-ha.yaml to /var/lib/rancher/k3s/server/manifests/ and run" \
    "deploy/k3s/traefik-ha.sh; elsewhere run your ingress with two copies on different nodes"
else
  echo "ok: Traefik ready on $traefik nodes"
fi

if [ "$(kubectl -n "$NAMESPACE" get pods -l app.kubernetes.io/part-of=supportx -o name 2>/dev/null | count)" = 0 ]; then
  echo "skipped: no SupportX release in namespace $NAMESPACE yet (set SUPPORTX_NAMESPACE); its" \
    "checks run after the install"
else
  nats="$(pod_nodes "$NAMESPACE" app.kubernetes.io/name=nats,app.kubernetes.io/component=nats)"
  if [ "$(echo "$nats" | count)" = 0 ]; then
    warn "no NATS pods in $NAMESPACE (app.kubernetes.io/name=nats)"
  elif [ "$(echo "$nats" | sort -u | count)" -lt 2 ] ||
    [ "$(echo "$nats" | sort | uniq -d | count)" -gt 0 ]; then
    warn "NATS servers share a node ($(echo "$nats" | sort | uniq -c | awk '{print $2 " x" $1}' | paste -sd, -)):" \
      "losing it can take JetStream's quorum. Install with values-ha.yaml (required anti-affinity)"
  else
    echo "ok: NATS servers on $(echo "$nats" | count) distinct nodes"
  fi

  pg="$(pod_nodes "$NAMESPACE" cnpg.io/podRole=instance)"
  if [ "$(echo "$pg" | count)" = 0 ]; then
    echo "skipped: no CloudNativePG instances in $NAMESPACE (external database?)"
  elif [ "$(echo "$pg" | sort | uniq -d | count)" -gt 0 ]; then
    warn "PostgreSQL instances share a node ($(echo "$pg" | sort | uniq -c | awk '{print $2 " x" $1}' | paste -sd, -)):" \
      "losing it can take the primary and its standby together. Install with values-ha.yaml" \
      "(CloudNativePG podAntiAffinityType required)"
  else
    echo "ok: PostgreSQL instances on $(echo "$pg" | count) distinct nodes"
  fi

  for component in fanout indexes; do
    slow="$(slow_eviction_pods "$NAMESPACE" "app.kubernetes.io/part-of=supportx,app.kubernetes.io/component=$component")"
    if [ -n "$slow" ]; then
      warn "$component runs one copy without the fast-eviction tolerations ($(echo "$slow" | paste -sd, -)):" \
        "on a lost node it waits five minutes to move. Install with values-ha.yaml (ha.fastEvictionSeconds)"
    else
      echo "ok: $component has the fast-eviction tolerations"
    fi
  done

  if [ "$(kubectl -n "$NAMESPACE" get statefulsets -l app.kubernetes.io/part-of=supportx,app.kubernetes.io/component=seaweedfs -o name | count)" -gt 0 ]; then
    advise "the bundled SeaweedFS runs in $NAMESPACE: one copy, not highly available. While its" \
      "node is down, attachments cannot be uploaded or opened. HA installs use their own" \
      "S3-compatible store (MinIO cluster, Ceph RGW, cloud S3): objectStorage.mode=external" \
      "(docs/deployment.md, Profiles)"
  fi
fi

# Not checkable from inside the cluster, so a reminder, never a warning (docs/deployment.md,
# "Front load balancer"): a lost or just-rejoined node drops requests only if the load balancer
# in front of the nodes keeps sending to it.
echo "note: the load balancer in front of the nodes must health-check each node's ingress port (80/443) and skip failing nodes; DNS round robin alone is not HA (docs/deployment.md)"
[ "$advisories" -gt 0 ] && echo "ha-preflight: $advisories advisory warning(s) (never fail the check)"
if [ "$warnings" -gt 0 ]; then
  echo "ha-preflight: $warnings warning(s)"
  [ "${HA_PREFLIGHT_STRICT:-0}" = 1 ] && exit 1
else
  echo "ha-preflight: every check passed"
fi
exit 0
