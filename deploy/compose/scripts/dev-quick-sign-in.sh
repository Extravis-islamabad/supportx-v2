#!/usr/bin/env bash
# DEV ONLY (D-151): switch on the quick sign-in for the local stack. Never on a real installation:
# the API refuses it with any profile but dev, and the Helm chart refuses to render it.
#
#   1. deploy/compose/.env: a SHOWCASE_TOTP_KEY (random, only if none) and DEV_QUICK_SIGN_IN=true.
#      The key never leaves this machine: it is not committed and never printed.
#   2. backend/.env: the three SUPPORTX_* settings the API reads (added or updated).
# Then `make showcase-seed` (run by `make dev-quick-sign-in`) enrols the personas' authenticators.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
DEV_ENV="$ROOT/deploy/compose/.env"
BACKEND_ENV="$ROOT/backend/.env"

value() { grep "^$1=" "$DEV_ENV" | cut -d= -f2- || true; }
set_line() {  # file name value: replace the line, or add it
  local file="$1" name="$2" val="$3"
  if grep -q "^$name=" "$file" 2>/dev/null; then
    local tmp; tmp="$(mktemp)"
    awk -v n="$name" -v v="$val" 'BEGIN{FS=OFS="="} $1==n{print n"="v; next} {print}' "$file" > "$tmp"
    cat "$tmp" > "$file" && rm -f "$tmp"
  else
    printf '%s=%s\n' "$name" "$val" >> "$file"
  fi
}

if [ -z "$(value SHOWCASE_PASSWORD)" ]; then
  echo "dev-quick-sign-in: set SHOWCASE_PASSWORD in deploy/compose/.env first (see docs/dev-setup.md)" >&2
  exit 1
fi
if [ -z "$(value SHOWCASE_TOTP_KEY)" ]; then
  set_line "$DEV_ENV" SHOWCASE_TOTP_KEY "$(openssl rand -hex 32)"
  echo "dev-quick-sign-in: made a new SHOWCASE_TOTP_KEY in deploy/compose/.env (not shown)"
fi
set_line "$DEV_ENV" DEV_QUICK_SIGN_IN true
test -f "$BACKEND_ENV" || bash "$ROOT/deploy/compose/scripts/backend-env.sh"
set_line "$BACKEND_ENV" SUPPORTX_DEV_QUICK_SIGN_IN true
set_line "$BACKEND_ENV" SUPPORTX_SHOWCASE_PASSWORD "$(value SHOWCASE_PASSWORD)"
set_line "$BACKEND_ENV" SUPPORTX_SHOWCASE_TOTP_KEY "$(value SHOWCASE_TOTP_KEY)"
echo "dev-quick-sign-in: on in backend/.env (dev profile only)"
