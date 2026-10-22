#!/usr/bin/env bash
# Deletes the SupportX dev stack's containers AND its data volumes, after explicit confirmation.
# Touches only volumes this compose project declares (supportx_dev_*), never anything else.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
compose=(docker compose --project-directory "$here" -f "$here/docker-compose.yml" --profile full --profile setup)

volumes="$("${compose[@]}" config --volumes 2>/dev/null | while read -r v; do
  docker volume ls -q --filter "name=^supportx_dev_${v}$"
done)"

echo "This stops the SupportX dev stack and PERMANENTLY DELETES its local data:"
if [[ -n "$volumes" ]]; then
  printf '  - %s\n' $volumes
else
  echo "  (no supportx_dev_* volumes exist yet)"
fi
echo "Databases, Keycloak users, buckets, mail and search indexes in these volumes cannot be recovered."
echo "deploy/compose/.env is kept."
printf 'Type "yes" to delete, anything else to cancel: '
read -r answer
if [[ "$answer" != "yes" ]]; then
  echo "Cancelled. Nothing was deleted."
  exit 1
fi

"${compose[@]}" down --volumes --remove-orphans
echo "Dev stack reset. Run 'make dev-up' to start again with empty data."
