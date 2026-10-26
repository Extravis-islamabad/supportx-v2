#!/usr/bin/env bash
# ClamAV signatures for air-gapped installations (WP-022, D-082 D3; docs/architecture/files.md).
#
#   deploy/scripts/clamav-signatures.sh fetch <dir>               on a machine with internet
#   deploy/scripts/clamav-signatures.sh load  <dir> [namespace]   inside the installation
#
# `fetch` downloads the current main, daily and bytecode databases into <dir> with the same ClamAV
# image the chart runs (no other tool needed). Carry <dir> into the site like any other installer
# artefact. `load` copies them into the release's ClamAV volume; clamd picks them up within 10
# minutes (SelfCheck), and the "signatures older than 7 days" alert clears. Repeat at least weekly.
# A private mirror (values: clamav.privateMirror) makes this automatic instead.
set -euo pipefail
IMAGE="${CLAMAV_IMAGE:-clamav/clamav:1.5.4-debian}"
command="${1:-}"
dir="${2:-}"
[[ -n "$command" && -n "$dir" ]] || {
  echo "usage: $0 fetch|load <dir> [namespace]" >&2
  exit 2
}
case "$command" in
  fetch)
    mkdir -p "$dir"
    dir="$(cd "$dir" && pwd)"
    conf="$(mktemp)"
    trap 'rm -f "$conf"' EXIT
    printf 'DatabaseDirectory /signatures\nDatabaseMirror database.clamav.net\n' >"$conf"
    docker run --rm --user "$(id -u):$(id -g)" -v "$dir:/signatures" -v "$conf:/freshclam.conf:ro" \
      --entrypoint freshclam "$IMAGE" --foreground --config-file=/freshclam.conf
    ls -l "$dir"
    ;;
  load)
    namespace="${3:-supportx}"
    pod="$(kubectl -n "$namespace" get pods -l app.kubernetes.io/component=clamav \
      -o jsonpath='{.items[0].metadata.name}')"
    [[ -n "$pod" ]] || {
      echo "no ClamAV pod in namespace $namespace (is clamav.enabled on?)" >&2
      exit 1
    }
    for file in "$dir"/*.cvd "$dir"/*.cld; do
      [[ -e "$file" ]] || continue
      kubectl -n "$namespace" cp "$file" "$pod:/var/lib/clamav/$(basename "$file")" -c freshclam
      echo "loaded $(basename "$file")"
    done
    ;;
  *)
    echo "unknown command: $command (fetch or load)" >&2
    exit 2
    ;;
esac
