#!/usr/bin/env bash
# docker compose for the dev stack, refusing a second project on the shared stack's volumes.
#
# The compose file names its data volumes ${SUPPORTX_VOLUME_PREFIX:-supportx_dev}_*: unset, they
# are the shared dev stack's own. A different project name (`-p`, `--project-name` or
# COMPOSE_PROJECT_NAME) with the default prefix would mount that stack's PostgreSQL data from a
# second server and corrupt it (the 2026-11-20 incident). So that combination is refused here:
# give a throwaway stack its own prefix, e.g.
#   SUPPORTX_VOLUME_PREFIX=throwaway_e2e deploy/compose/scripts/compose.sh -p throwaway-e2e up -d
set -euo pipefail

DEFAULT_PROJECT="supportx-dev"
DEFAULT_PREFIX="supportx_dev"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

project="${COMPOSE_PROJECT_NAME:-$DEFAULT_PROJECT}"
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  case "${args[$i]}" in
    -p | --project-name) project="${args[$((i + 1))]:-}" ;;
    -p?*) project="${args[$i]#-p}" ;;
    --project-name=*) project="${args[$i]#--project-name=}" ;;
  esac
done
prefix="${SUPPORTX_VOLUME_PREFIX:-$DEFAULT_PREFIX}"

if [[ "$project" != "$DEFAULT_PROJECT" && "$prefix" == "$DEFAULT_PREFIX" ]]; then
  echo "refused: project '$project' would use the shared dev stack's volumes (${DEFAULT_PREFIX}_*)." >&2
  echo "Set SUPPORTX_VOLUME_PREFIX to a name of its own for this stack." >&2
  exit 3
fi
if [[ "$project" == "$DEFAULT_PROJECT" && "$prefix" != "$DEFAULT_PREFIX" ]]; then
  echo "refused: the shared dev stack ('$DEFAULT_PROJECT') keeps its own volumes; unset SUPPORTX_VOLUME_PREFIX." >&2
  exit 3
fi
exec docker compose --project-directory "$here" -f "$here/docker-compose.yml" "$@"
