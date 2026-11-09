#!/usr/bin/env bash
# The chart's pinned dependencies (NATS, Valkey) from Chart.lock (make chart-deps).
#
# A download from GitHub's release storage can time out (a 504 on valkey-0.12.0.tgz turned five
# nightly jobs red on 2026-11-08), so:
#   - tarballs already in charts/ at the locked versions are used as they are (CI restores them
#     with actions/cache keyed on Chart.lock, so a changed lock always downloads again);
#   - otherwise the download is tried up to CHART_DEPS_ATTEMPTS times, waiting 15 s, 30 s, 60 s.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CHART="$ROOT/deploy/helm/supportx"
ATTEMPTS="${CHART_DEPS_ATTEMPTS:-4}"

# "name version" per dependency in Chart.lock.
locked() {
  awk '/^- name:/ {name=$3} /^  version:/ {print name, $2}' "$CHART/Chart.lock"
}

all_present() {
  local name version
  while read -r name version; do
    [[ -s "$CHART/charts/$name-$version.tgz" ]] || return 1
  done < <(locked)
}

if all_present; then
  echo "chart-deps: every locked chart is in charts/ already ($(locked | tr '\n' ' '))"
  exit 0
fi

wait_s=15
for attempt in $(seq 1 "$ATTEMPTS"); do
  if helm repo add nats https://nats-io.github.io/k8s/helm/charts/ --force-update >/dev/null \
    && helm repo add valkey https://valkey.io/valkey-helm/ --force-update >/dev/null \
    && helm dependency build "$CHART"; then
    all_present && exit 0
    echo "chart-deps: helm finished but a locked tarball is missing" >&2
  fi
  if (( attempt < ATTEMPTS )); then
    echo "chart-deps: attempt $attempt of $ATTEMPTS failed; trying again in ${wait_s}s" >&2
    sleep "$wait_s"
    wait_s=$(( wait_s * 2 ))
  fi
done
echo "chart-deps: the chart dependencies could not be downloaded after $ATTEMPTS attempts" >&2
exit 1
