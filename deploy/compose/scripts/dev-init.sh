#!/usr/bin/env bash
# Creates deploy/compose/.env from .env.example, replacing each `__generate__` with a random
# secret. If .env already exists, only keys it does not have yet are appended (new settings arrive
# with fresh secrets); existing values are never changed, because the data volumes were initialised
# with them.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
example="$here/.env.example"
target="$here/.env"

render() { # line -> line with a fresh secret if it asks for one
  local line="$1"
  if [[ "$line" == *=__generate__ ]]; then
    # Hex only: safe inside URLs, connection strings and shell without quoting.
    line="${line%__generate__}$(openssl rand -hex 16)"
  fi
  printf '%s\n' "$line"
}

if [[ ! -f "$target" ]]; then
  tmp="$(mktemp "$here/.env.XXXXXX")"
  trap 'rm -f "$tmp"' EXIT
  while IFS= read -r line || [[ -n "$line" ]]; do
    render "$line"
  done <"$example" >"$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$target"
  trap - EXIT
  echo "Created deploy/compose/.env with fresh random dev secrets."
  exit 0
fi

added=0
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ "$line" =~ ^([A-Z0-9_]+)= ]] || continue
  key="${BASH_REMATCH[1]}"
  if ! grep -q "^${key}=" "$target"; then
    render "$line" >>"$target"
    added=$((added + 1))
  fi
done <"$example"
if ((added > 0)); then
  echo "deploy/compose/.env: added ${added} new setting(s); existing values left unchanged."
else
  echo "deploy/compose/.env is up to date; left unchanged."
fi
