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
  "external-db|-f $CHART/values-single-node.yaml --set publicUrl=https://supportx.example.com --set routing.gateway.tlsSecret=supportx-tls --set postgresql.mode=external --set postgresql.external.host=db.example.com"
  "podmonitors|-f $CHART/values-dev.yaml --set metrics.podMonitors=true"
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
