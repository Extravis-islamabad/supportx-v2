#!/usr/bin/env bash
# Playwright inside the pinned Playwright image, on the host's network (the `run` part of
# action.yml; cluster.yml also calls it from e2e.sh through a pnpm shim).
#
#   run.sh <playwright cli args...>       e.g. run.sh test tests/login.spec.ts
#
# Environment:
#   PLAYWRIGHT_IMAGE       required; exported by the action's `pull` part (one pinned digest).
#   PLAYWRIGHT_ENV_NAMES   names to pass in, one per line, each as `-e NAME` (never a value).
#   PLAYWRIGHT_ADD_HOSTS   extra /etc/hosts entries, one `host:ip` per line.
#   GITHUB_WORKSPACE, RUNNER_TEMP  from the runner.
#
# On the host's network, the stack, Keycloak's issuer and the Vite servers stay on the runner's
# localhost (GitHub refuses --network host for job containers, so this is a plain `docker run`).
# The repo is mounted at its own path, so the absolute paths in backend/.venv and the e2e
# package's REPO resolve unchanged, and reports and screenshots land in the workspace. Node and
# the browsers are the image's (/ms-playwright); the test runner and node_modules are the host's
# pnpm install (setup-frontend). The global setup and teardown also run backend tools (`uv run
# python -m tooling.…`, `make dev-subscription`), which the image lacks: the host's uv and make
# binaries (same Ubuntu 24.04 glibc) are mounted read-only on /opt/host-tools, and the venv's
# Python install at its own path, with uv told not to sync (the host already did). The image's
# Node is newer than .nvmrc's; Playwright transpiles the e2e TypeScript itself.
set -euo pipefail

: "${PLAYWRIGHT_IMAGE:?run the playwright-in-image action with part: pull first}"
workspace="${GITHUB_WORKSPACE:?}"
(( $# > 0 )) || { echo "::error::run.sh needs Playwright CLI arguments" >&2; exit 1; }

# Only the uv-managed Python install (setup-backend), never a system prefix like /usr.
python_home="$(dirname "$(dirname "$(readlink -f "$workspace/backend/.venv/bin/python")")")"
case "$python_home" in
  /|/usr|/usr/local) echo "::error::backend/.venv uses a system Python ($python_home)" >&2; exit 1 ;;
esac

home="${RUNNER_TEMP:?}/playwright-home"
mkdir -p "$home"

passed=()
while IFS= read -r name; do
  [[ -z "$name" ]] && continue
  [[ "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || {
    echo "::error::not an environment variable name: '$name'" >&2; exit 1; }
  passed+=(-e "$name")
done <<< "${PLAYWRIGHT_ENV_NAMES:-}"

# One `host:ip` per entry: a DNS name, then an IPv4 address or docker's literal host-gateway.
# Anything else fails here with the entry named, not later as an unclear docker error.
octet='(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])'
ipv4="^${octet}\.${octet}\.${octet}\.${octet}$"
hostname_re='^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$'
hosts=()
while IFS= read -r entry; do
  [[ -z "$entry" ]] && continue
  host="${entry%%:*}"
  ip="${entry#*:}"
  if [[ "$entry" != *:* || ! "$host" =~ $hostname_re ]] \
    || [[ "$ip" != "host-gateway" && ! "$ip" =~ $ipv4 ]]; then
    echo "::error::add-hosts entry '$entry' is not host:ip (an IPv4 address or host-gateway)" >&2
    exit 1
  fi
  hosts+=(--add-host "$entry")
done <<< "${PLAYWRIGHT_ADD_HOSTS:-}"

set -x
docker run --rm --network host --user "$(id -u):$(id -g)" \
  -v "$workspace:$workspace" -w "$workspace/frontend/e2e" \
  -v "$home:$home" -e HOME="$home" \
  -v "$(command -v uv):/opt/host-tools/uv:ro" -v "$(command -v make):/opt/host-tools/make:ro" \
  -v "$python_home:$python_home:ro" \
  -e PATH="/opt/host-tools:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  -e UV_NO_SYNC=1 -e UV_FROZEN=1 -e UV_CACHE_DIR="$home/uv-cache" -e UV_PYTHON_DOWNLOADS=never \
  -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright -e CI \
  ${passed[@]+"${passed[@]}"} ${hosts[@]+"${hosts[@]}"} \
  "$PLAYWRIGHT_IMAGE" \
  node node_modules/@playwright/test/cli.js "$@"
