#!/usr/bin/env bash
# Lint and validate the supportx chart for every profile (make chart-lint; CI on every PR, WP-014).
#
#   1. helm lint --strict per profile
#   2. helm template per profile, validated by kubeconform against the Kubernetes 1.36 schemas and
#      the CRD schemas (CloudNativePG, Gateway API, Prometheus Operator) from a pinned catalog
#   3. the single-node output is compared with the committed golden file, so every change to
#      what customers would install shows up in review (UPDATE_GOLDEN=1 rewrites it)
#
# Rendered manifests are left in $CHART_RENDER_DIR (default: a temp dir) for the Trivy config scan.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CHART="$ROOT/deploy/helm/supportx"
OUT="${CHART_RENDER_DIR:-$(mktemp -d)}"
mkdir -p "$OUT"
K8S_VERSION="1.36.5"
# datreeio/CRDs-catalog at a fixed commit: schema changes upstream never break CI silently.
CRDS_CATALOG="https://raw.githubusercontent.com/datreeio/CRDs-catalog/501527ab9c40"

# name | values files and flags
PROFILES=(
  "dev|-f $CHART/values-dev.yaml"
  "single-node|-f $CHART/values-single-node.yaml --set publicUrl=https://supportx.example.com --set routing.hostnames={supportx.example.com} --set routing.gateway.tlsSecret=supportx-tls"
  "ingress|-f $CHART/values-single-node.yaml --set publicUrl=https://supportx.example.com --set routing.mode=ingress --set routing.ingress.tlsSecret=supportx-tls --set routing.hostnames={supportx.example.com}"
  "external-db|-f $CHART/values-single-node.yaml --set publicUrl=https://supportx.example.com --set routing.gateway.tlsSecret=supportx-tls --set postgresql.mode=external --set postgresql.external.host=db.example.com --set temporal.bundled.enabled=false --set temporal.address=temporal.example.com:7233"
  "podmonitors|-f $CHART/values-dev.yaml --set metrics.podMonitors=true"
  "ha-ci|-f $CHART/values-dev.yaml -f $CHART/values-ha.yaml -f $CHART/values-ha-ci.yaml --set networkPolicies.egress.kubeApiCidrs={10.0.0.10/32}"
  "ha|-f $CHART/values-ha.yaml --set publicUrl=https://supportx.example.com --set routing.hostnames={supportx.example.com} --set routing.gateway.tlsSecret=supportx-tls"
  "backups|-f $CHART/values-ha.yaml --set publicUrl=https://supportx.example.com --set routing.hostnames={supportx.example.com} --set routing.gateway.tlsSecret=supportx-tls --set postgresql.cnpg.backup.enabled=true"
  "ldap|-f $CHART/values-single-node.yaml --set publicUrl=https://supportx.example.com --set routing.hostnames={supportx.example.com} --set routing.gateway.tlsSecret=supportx-tls --set directory.ldap.enabled=true"
  "ai-models|-f $CHART/values-single-node.yaml --set publicUrl=https://supportx.example.com --set routing.hostnames={supportx.example.com} --set routing.gateway.tlsSecret=supportx-tls --set ai.local.enabled=true"
  "ai-gpu|-f $CHART/values-single-node.yaml --set publicUrl=https://supportx.example.com --set routing.hostnames={supportx.example.com} --set routing.gateway.tlsSecret=supportx-tls --set ai.local.enabled=true --set ai.gpu.enabled=true --set ai.gpu.resourceName=nvidia.com/gpu"
)

for entry in "${PROFILES[@]}"; do
  name="${entry%%|*}"
  # shellcheck disable=SC2086 # the flags are meant to be split
  args=(${entry#*|})
  echo "== $name"
  helm lint "$CHART" --strict "${args[@]}" --quiet
  helm template supportx "$CHART" --namespace supportx "${args[@]}" > "$OUT/$name.yaml"
  if command -v kubeconform >/dev/null 2>&1; then
    kubeconform -strict -summary -kubernetes-version "$K8S_VERSION" \
      -schema-location default \
      -schema-location "$CRDS_CATALOG/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json" \
      "$OUT/$name.yaml"
  else
    echo "kubeconform not installed: schema validation skipped (CI always runs it)"
  fi
done

# On-prem LDAP (D-118, product owner 2026-11-03): the federation secret reaches exactly the
# keycloak-identity Job and the consumers worker with LDAP on, no pod without it, and the chart
# refuses LDAP on a multi-tenant installation (a shared realm would show its people to everyone).
federation_pods() { grep -c 'SUPPORTX_KEYCLOAK_FEDERATION_CLIENT_SECRET' "$1" || true; }
[ "$(federation_pods "$OUT/ldap.yaml")" = "2" ] || { echo "ldap: the federation secret must reach exactly 2 pods" >&2; exit 1; }
[ "$(federation_pods "$OUT/single-node.yaml")" = "0" ] || { echo "single-node: no pod may hold the federation secret without LDAP" >&2; exit 1; }
LDAP_ARGS=""  # found by name, so adding a profile never shifts it
for entry in "${PROFILES[@]}"; do [ "${entry%%|*}" = ldap ] && LDAP_ARGS="${entry#*|}"; done
[ -n "$LDAP_ARGS" ] || { echo "chart-lint: no ldap profile" >&2; exit 1; }
# shellcheck disable=SC2086 # the flags are meant to be split
if helm template supportx "$CHART" --namespace supportx $LDAP_ARGS --set multiTenant=true >/dev/null 2>&1; then
  echo "ldap: the chart must refuse directory.ldap.enabled with multiTenant: true" >&2
  exit 1
fi
# HA (WP-014b): every SupportX Deployment that runs more than one copy (or scales), and the
# PgBouncer Pooler, has a PodDisruptionBudget of the same name and podAntiAffinity, so losing or
# draining one node never takes every copy. The Pooler must run more than one copy: every API
# request goes through it (the node-loss test lost the only one).
awk '
  /^---/ { flush(); kind = ""; name = ""; copies = 0; anti = 0; next }
  /^kind: / { kind = $2 }
  /^  name: supportx-/ && name == "" { name = $2 }
  /^  replicas: [0-9]+/ { copies = $2 }
  /^  minReplicas: [0-9]+/ { copies = $2 }
  /^  instances: [0-9]+/ { copies = $2 }
  /podAntiAffinity:/ { anti = 1 }
  function flush() {
    if (kind == "Deployment" && copies > 1) { multi[name] = 1; if (!anti) bare[name] = 1 }
    if (kind == "HorizontalPodAutoscaler") { multi[name] = 1 }
    if (kind == "Pooler") { poolers++; if (copies > 1) { multi[name] = 1; if (!anti) bare[name] = 1 } else single[name] = 1 }
    if (kind == "PodDisruptionBudget") { pdb[name] = 1 }
  }
  END {
    flush(); bad = 0
    if (poolers == 0) { print "HA: no PgBouncer Pooler rendered"; bad = 1 }
    for (n in single) { print "HA: " n " runs one copy"; bad = 1 }
    for (n in multi) {
      if (!(n in pdb)) { print "HA: " n " runs several copies without a PodDisruptionBudget"; bad = 1 }
      if (n in bare) { print "HA: " n " runs several copies without podAntiAffinity"; bad = 1 }
    }
    exit bad
  }
' "$OUT/ha.yaml" || { echo "HA profile check failed"; exit 1; }
echo "HA: every multi-copy component has a PodDisruptionBudget and anti-affinity"

# Egress allow-list (WP-014b): offline (helm template, GitOps) the chart can't read the control
# plane's addresses, so with egress on and no kubeApiCidrs it must refuse, never fall back to an
# open 0.0.0.0/0. With them set (the ha-ci profile above) every kube-API rule uses exactly them.
if helm template supportx "$CHART" --namespace supportx -f "$CHART/values-dev.yaml" \
  --set networkPolicies.egress.enabled=true >/dev/null 2>"$OUT/egress-refused.txt"; then
  echo "egress: the chart must refuse egress on without kubeApiCidrs when it can't read the cluster" >&2
  exit 1
fi
grep -q "kubeApiCidrs" "$OUT/egress-refused.txt" || { echo "egress: the refusal must name kubeApiCidrs" >&2; exit 1; }
# Only the egress policies: dev-only ingress rules (NodePorts) use 0.0.0.0/0 on purpose.
if awk '/^---/ { if (egress && open) found = 1; egress = 0; open = 0 }
        /policyTypes: \[Egress\]/ { egress = 1 }
        /0\.0\.0\.0\/0/ { open = 1 }
        END { if (egress && open) found = 1; exit !found }' "$OUT/ha-ci.yaml"; then
  echo "egress: no egress rule may allow 0.0.0.0/0 (ha-ci)" >&2; exit 1
fi
echo "egress: refused without the control plane's addresses; no open 0.0.0.0/0 rule"

# Backups (WP-014b): the in-cluster dev target renders as it is; any external target must be
# encrypted at rest, by `encryption` or a stated bucket policy, or the chart refuses (fails closed).
BK="helm template supportx $CHART --namespace supportx -f $CHART/values-dev.yaml --set postgresql.cnpg.backup.enabled=true"
EXT="--set postgresql.cnpg.backup.endpointURL=https://s3.example.com --set postgresql.cnpg.backup.destinationPath=s3://backups/pg"
# shellcheck disable=SC2086 # the flags are meant to be split
$BK >/dev/null || { echo "backups: the in-cluster target must render" >&2; exit 1; }
# shellcheck disable=SC2086
if $BK $EXT >/dev/null 2>"$OUT/backup-refused.txt"; then
  echo "backups: an unencrypted external target must be refused" >&2; exit 1
fi
grep -q "encrypted at rest" "$OUT/backup-refused.txt" || { echo "backups: the refusal must say why" >&2; exit 1; }
# shellcheck disable=SC2086
$BK $EXT --set postgresql.cnpg.backup.encryption=AES256 >/dev/null || { echo "backups: an encrypted external target must render" >&2; exit 1; }
# shellcheck disable=SC2086
$BK $EXT --set postgresql.cnpg.backup.encryptionByBucketPolicy=true >/dev/null || { echo "backups: a stated bucket policy must render" >&2; exit 1; }
echo "backups: in-cluster renders; external refused unless encrypted (value or bucket policy)"

# Local AI (WP-037): off by default; on, every weight file is checked against its pinned sha256
# before the server starts, only the gateway's pods reach the servers, and the GPU node needs its
# device plugin's resource name (no vendor assumed).
[ "$(grep -c 'llm-' "$OUT/single-node.yaml" || true)" = "0" ] || { echo "ai: the model servers must be off by default" >&2; exit 1; }
WEIGHTS="$(grep -c 'sha256sum -c' "$OUT/ai-models.yaml" || true)"
[ "$WEIGHTS" = "2" ] || { echo "ai-models: both CPU servers must check their weights ($WEIGHTS)" >&2; exit 1; }
grep -q "llm-ingress" "$OUT/ai-models.yaml" || { echo "ai-models: the servers need their ingress policy" >&2; exit 1; }
AI_ARGS=""
for entry in "${PROFILES[@]}"; do [ "${entry%%|*}" = ai-models ] && AI_ARGS="${entry#*|}"; done
# shellcheck disable=SC2086 # the flags are meant to be split
if helm template supportx "$CHART" --namespace supportx $AI_ARGS --set ai.gpu.enabled=true >/dev/null 2>&1; then
  echo "ai-gpu: the chart must refuse a GPU node without ai.gpu.resourceName" >&2; exit 1
fi
echo "ai: off by default; weights checked before start; GPU resource required"

# The bundled Temporal needs this release's CloudNativePG cluster: with an external database the
# chart refuses it (run Temporal yourself and set temporal.address).
EXT_ARGS=""
for entry in "${PROFILES[@]}"; do [ "${entry%%|*}" = external-db ] && EXT_ARGS="${entry#*|}"; done
# shellcheck disable=SC2086 # the flags are meant to be split
if helm template supportx "$CHART" --namespace supportx $EXT_ARGS --set temporal.bundled.enabled=true >/dev/null 2>&1; then
  echo "temporal: the chart must refuse the bundled Temporal with an external database" >&2; exit 1
fi
echo "temporal: bundled only on the release's CloudNativePG cluster"

# Transport security (audit row 5; docs/deployment.md). HTTPS at the gateway by default: the app
# routes hang off the HTTPS listener and plain HTTP only redirects (301). The dev profile (the
# local k3d cluster, plain http on supportx.localhost) keeps one HTTP listener and no redirect.
for p in single-node ha; do
  grep -q "name: supportx-https-redirect" "$OUT/$p.yaml" || { echo "$p: no http-to-https redirect" >&2; exit 1; }
  [ "$(grep -c 'protocol: HTTPS' "$OUT/$p.yaml" || true)" = "1" ] || { echo "$p: no HTTPS listener" >&2; exit 1; }
done
grep -q "protocol: HTTPS" "$OUT/dev.yaml" && { echo "dev: plain http on the local cluster only" >&2; exit 1; }
grep -q "supportx-https-redirect" "$OUT/dev.yaml" && { echo "dev: no redirect on the local cluster" >&2; exit 1; }
SN="-f $CHART/values-single-node.yaml"
# shellcheck disable=SC2086 # the flags are meant to be split
if helm template supportx "$CHART" --namespace supportx $SN --set publicUrl=https://supportx.example.com >/dev/null 2>&1; then
  echo "routing: TLS on without a certificate (secretName or issuerRef) must be refused" >&2; exit 1
fi
# shellcheck disable=SC2086
if helm template supportx "$CHART" --namespace supportx $SN --set publicUrl=http://supportx.example.com \
  --set routing.tls.secretName=t >/dev/null 2>&1; then
  echo "routing: TLS on with an http:// publicUrl must be refused" >&2; exit 1
fi
# shellcheck disable=SC2086
helm template supportx "$CHART" --namespace supportx $SN --set publicUrl=https://supportx.example.com \
  --set routing.tls.issuerRef.name=corp --set routing.tls.issuerRef.kind=ClusterIssuer \
  --show-only templates/routing.yaml | grep -q "kind: Certificate" ||
  { echo "routing: issuerRef must render a cert-manager Certificate" >&2; exit 1; }
echo "transport: HTTPS with an http redirect by default; dev plain http; misconfigurations refused"

# The golden file is what an install creates: without `helm test` pods (those run on demand).
GOLDEN="$CHART/tests/golden/single-node.yaml"
SN_ARGS="${PROFILES[1]#*|}"
# shellcheck disable=SC2086 # the flags are meant to be split
# The breached-password list (about 47,000 lines) stands in the golden file as its checksum, so a
# change to it still shows up in review without burying everything else.
LIST="$CHART/files/keycloak/password-blacklists/supportx-breached.txt"
LIST_SUM="$(shasum -a 256 "$LIST" | cut -d' ' -f1)"
helm template supportx "$CHART" --namespace supportx --skip-tests $SN_ARGS |
  awk -v sum="$LIST_SUM" '
    skipping && (/^    / || /^$/) { next }
    skipping { skipping = 0 }
    { print }
    /^  supportx-breached.txt: \|$/ { print "    # sha256 " sum " (files/keycloak/password-blacklists)"; skipping = 1 }
  ' > "$OUT/single-node.installed.yaml"
if [ "${UPDATE_GOLDEN:-0}" = "1" ]; then
  mkdir -p "$(dirname "$GOLDEN")"
  cp "$OUT/single-node.installed.yaml" "$GOLDEN"
  echo "golden file updated: $GOLDEN"
elif ! diff -u "$GOLDEN" "$OUT/single-node.installed.yaml"; then
  echo "single-node render differs from $GOLDEN: review, then UPDATE_GOLDEN=1 make chart-lint" >&2
  exit 1
fi
echo "chart OK (rendered manifests in $OUT)"
