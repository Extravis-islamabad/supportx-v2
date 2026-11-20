#!/usr/bin/env bash
# docker compose for the dev stack, refusing a second project on the shared stack's volumes.
#
# The compose file names its data volumes ${SUPPORTX_VOLUME_PREFIX:-supportx_dev}_*: unset, they
# are the shared dev stack's own. A project other than supportx-dev on those volumes would run a
# second PostgreSQL on the shared data directory and corrupt it (the 2026-11-20 incident).
#
# The project and the prefix can come from flags, the shell, deploy/compose/.env or --env-file,
# so this asks compose itself: `config --format json` with the same global options gives the
# project's resolved name and every volume's resolved name, and the call is refused when
#   - the project isn't supportx-dev and any volume is a shared one (supportx_dev_*), or
#   - the project is supportx-dev and any volume isn't (the shared stack keeps its own).
# Give a throwaway stack its own prefix, e.g.
#   SUPPORTX_VOLUME_PREFIX=throwaway_e2e deploy/compose/scripts/compose.sh -p throwaway-e2e up -d
set -euo pipefail

DEFAULT_PROJECT="supportx-dev"
SHARED_PREFIX="supportx_dev_"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
base=(compose --project-directory "$here" -f "$here/docker-compose.yml")

# The global options: everything before the subcommand (so `run -p 5432:5432` is a port, not a
# project). Options that take a value take the next word too.
globals=()
args=("$@")
i=0
while ((i < ${#args[@]})); do
  word="${args[$i]}"
  case "$word" in
    -p | --project-name | --env-file | --profile | -f | --file | --project-directory | --ansi | \
      --progress | --parallel)
      globals+=("$word" "${args[$((i + 1))]:-}")
      i=$((i + 2))
      ;;
    -*) # --dry-run, --compatibility, -pNAME, --project-name=NAME, --env-file=FILE ...
      globals+=("$word")
      i=$((i + 1))
      ;;
    *) break ;;
  esac
done

errors="$(mktemp)"
trap 'rm -f "$errors"' EXIT
# ${a[@]+"${a[@]}"}: an empty array is "unbound" to bash 3.2 (macOS) under `set -u`.
if ! resolved="$(docker "${base[@]}" ${globals[@]+"${globals[@]}"} config --format json 2>"$errors")"; then
  # compose can't resolve the project (e.g. no .env yet): never run unchecked, show its error.
  cat "$errors" >&2
  echo "refused: compose could not resolve the project to check its volumes." >&2
  exit 3
fi
verdict="$(
  printf '%s' "$resolved" | python3 -c '
import json, sys
config = json.load(sys.stdin)
name = config.get("name", "")
volumes = [v.get("name", "") for v in (config.get("volumes") or {}).values()]
shared = [v for v in volumes if v.startswith(sys.argv[2])]
if name != sys.argv[1] and shared:
    print(f"refused: project {name!r} would use the shared dev stack volumes: {shared}.")
    print("Set SUPPORTX_VOLUME_PREFIX to a name of its own for this stack.")
elif name == sys.argv[1] and len(shared) != len(volumes):
    print("refused: the shared dev stack keeps its own volumes; unset SUPPORTX_VOLUME_PREFIX.")
' "$DEFAULT_PROJECT" "$SHARED_PREFIX"
)"
if [[ -n "$verdict" ]]; then
  echo "$verdict" >&2
  exit 3
fi
rm -f "$errors"  # exec never runs the EXIT trap
exec docker "${base[@]}" "$@"
