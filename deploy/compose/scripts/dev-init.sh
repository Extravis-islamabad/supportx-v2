#!/usr/bin/env bash
# Creates deploy/compose/.env from .env.example, replacing each `__generate__` with a random
# secret. Never overwrites an existing .env: the data volumes were initialised with its values.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
example="$here/.env.example"
target="$here/.env"

if [[ -f "$target" ]]; then
  echo "deploy/compose/.env already exists; leaving it unchanged."
  exit 0
fi

tmp="$(mktemp "$here/.env.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
while IFS= read -r line || [[ -n "$line" ]]; do
  if [[ "$line" == *=__generate__ ]]; then
    # Hex only: safe inside URLs, connection strings and shell without quoting.
    line="${line%__generate__}$(openssl rand -hex 16)"
  fi
  printf '%s\n' "$line"
done <"$example" >"$tmp"
chmod 600 "$tmp"
mv "$tmp" "$target"
trap - EXIT
echo "Created deploy/compose/.env with fresh random dev secrets."
