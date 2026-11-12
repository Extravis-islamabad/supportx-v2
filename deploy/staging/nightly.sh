#!/usr/bin/env bash
# The staging laptop's nightly run (D-169; docs/runbooks/staging-laptop.md, step 7).
#
#   deploy/staging/nightly.sh                  (systemd: supportx-staging.service, as user sxstaging)
#
# Pull-based, never a CI runner: it pulls main into its own dedicated checkout, builds the
# INTERNAL/DEV images there (D-038), imports them into k3s, tops up the Secrets, upgrades the
# release and tests it. The same sequence an offline install runs, so it doubles as a rehearsal.
#
# On a failed upgrade Helm rolls back to the previous release (--rollback-on-failure, Helm 4's
# name for --atomic): the release that worked last night keeps running. Every run writes a dated
# log in LOG_DIR (kept KEEP_DAYS days) and the result in STATE_DIR/last-run.
#
# Settings come from /etc/supportx-staging/staging.env (SUPPORTX_STAGING_CONFIG to change it).
# The whole body sits in main(): bash reads it fully before running, so the `git reset` below
# may rewrite this very file safely. A changed version of this script takes effect the next night.
set -euo pipefail

main() {
  local config="${SUPPORTX_STAGING_CONFIG:-/etc/supportx-staging/staging.env}"
  if [[ -r "$config" ]]; then
    # The file is sourced as shell code by a job that runs `git reset --hard` and Helm as this
    # user: only root may be able to change it (install it root-owned, mode 0644).
    local owner mode
    read -r owner mode < <(stat -c '%u %a' "$config")
    if [[ "$owner" != 0 || $((8#$mode & 8#022)) != 0 ]]; then
      echo "nightly: $config must be owned by root and writable by root only (now uid $owner, mode $mode)" >&2
      exit 1
    fi
    # shellcheck source=/dev/null
    . "$config"
  fi
  CHECKOUT="${CHECKOUT:-/srv/supportx-staging/checkout}"
  NAMESPACE="${NAMESPACE:-supportx}"
  RELEASE="${RELEASE:-supportx}"
  LOG_DIR="${LOG_DIR:-/var/log/supportx-staging}"
  STATE_DIR="${STATE_DIR:-/var/lib/supportx-staging}"
  KEEP_DAYS="${KEEP_DAYS:-14}"
  HELM_TIMEOUT="${HELM_TIMEOUT:-15m}"
  PUBLIC_URL="${PUBLIC_URL:?set PUBLIC_URL in $config, e.g. https://sx-staging.lan}"
  CA_FILE="${CA_FILE:-/etc/supportx-staging/ca.crt}"
  LOCAL_VALUES="${LOCAL_VALUES:-/etc/supportx-staging/values-local.yaml}"

  mkdir -p "$LOG_DIR" "$STATE_DIR"
  STARTED="$(date -Is)"
  LOG="$LOG_DIR/nightly-$(date +%Y-%m-%d-%H%M%S).log"
  exec > >(tee -a "$LOG") 2>&1
  TEE_PID=$!

  # One run at a time (a manual start while the timer's run is still going waits for it).
  exec 9>"$STATE_DIR/lock"
  flock 9

  STEP="start"
  SHA="unknown"
  trap 'on_exit $?' EXIT

  step "check the dedicated checkout"
  # This job runs `git reset --hard`: it must never touch anyone's working copy. The marker is
  # created once, by hand, when the checkout is cloned for this job only (runbook step 7).
  if [[ ! -f "$CHECKOUT/.git/supportx-staging-dedicated" ]]; then
    echo "refusing: $CHECKOUT is not the job's dedicated checkout (no .git/supportx-staging-dedicated)"
    return 1
  fi
  cd "$CHECKOUT"

  step "pull main"
  git fetch --prune origin main
  git reset --hard origin/main
  # Untracked files that are not ignored; ignored ones (.venv, node_modules, chart tarballs)
  # stay as caches.
  git clean -fd
  SHA="$(git rev-parse --short=12 HEAD)"
  echo "main is at $SHA: $(git log -1 --format=%s)"

  step "install build dependencies (backend venv, frontend packages)"
  (cd backend && uv sync --frozen)
  (cd frontend && pnpm install --frozen-lockfile)

  step "make generated"
  make generated

  step "build images (tag $SHA)"
  # Tagged by commit, not `dev`: `helm rollback` then really returns to the older images.
  make images IMAGE_TAG="$SHA"

  step "import images into k3s"
  docker save "supportx-backend:$SHA" "supportx-worker:$SHA" "supportx-web:$SHA" \
    | sudo -n /usr/local/bin/k3s ctr images import -

  step "chart dependencies"
  make chart-deps

  step "secrets (adds missing keys only)"
  bash deploy/scripts/secrets.sh "$NAMESPACE"

  step "helm upgrade"
  # The first install is done by hand (runbook step 6). A failed first install under
  # --rollback-on-failure would uninstall, deleting the database cluster with it.
  if ! helm status "$RELEASE" -n "$NAMESPACE" >/dev/null 2>&1; then
    echo "no release $RELEASE in $NAMESPACE: do the first install by hand (runbook step 6)"
    return 1
  fi
  local values=(-f deploy/helm/supportx/values-single-node.yaml -f deploy/helm/supportx/values-staging.yaml)
  if [[ -f "$LOCAL_VALUES" ]]; then
    values+=(-f "$LOCAL_VALUES")
  fi
  helm upgrade --install "$RELEASE" deploy/helm/supportx -n "$NAMESPACE" "${values[@]}" \
    --set-string images.backend.tag="$SHA" \
    --set-string images.worker.tag="$SHA" \
    --set-string images.web.tag="$SHA" \
    --rollback-on-failure --wait --timeout "$HELM_TIMEOUT"

  step "helm test"
  # As the Makefile's HELM_TEST: the upstream Valkey auth test is excluded (our NetworkPolicy
  # refuses it).
  helm test "$RELEASE" -n "$NAMESPACE" --logs --filter '!name=supportx-valkey-test-auth-existing'

  step "smoke: $PUBLIC_URL/api/v1/ready"
  curl -fsS --max-time 30 --cacert "$CA_FILE" "$PUBLIC_URL/api/v1/ready"
  echo

  step "browser smoke suite"
  # Skipped on purpose for now (lane C, #462): `make e2e-smoke` targets the dev servers
  # (SUPPORTX_CONSOLE_URL/PORTAL_URL), and against a cluster it needs the SUPPORTX_E2E_* set
  # (Keycloak admin, the Centrifugo secret, persona passwords) and the private CA, as the
  # cluster-e2e job has. It would also write e2e users and records into staging, which is the
  # product owner's call. A staging-e2e-smoke target mirroring cluster-e2e comes later.
  echo "skipped: no staging browser smoke target yet (runbook 7.1, step 11)"

  step "tidy up"
  # Docker's copies are no longer needed once k3s holds them; older k3s images stay for rollback
  # until the kubelet's image garbage collection needs the disk.
  local image
  while read -r image; do
    [[ "$image" == *":$SHA" ]] || docker rmi "$image" >/dev/null || true
  done < <(docker images --format '{{.Repository}}:{{.Tag}}' \
    | grep -E '^supportx-(backend|worker|web):' || true)
  docker builder prune -f --filter until=168h >/dev/null || true
  find "$LOG_DIR" -maxdepth 1 -name 'nightly-*.log' -mtime +"$((KEEP_DAYS - 1))" -delete

  STEP="done"
}

step() {
  STEP="$1"
  echo
  echo "== $(date -Is) $STEP"
}

# shellcheck disable=SC2317 # on_exit runs from the EXIT trap, which shellcheck cannot see
on_exit() {
  local code="$1" result="ok"
  [[ "$code" == 0 && "$STEP" == "done" ]] || result="failed"
  {
    echo "result=$result"
    echo "step=$STEP"
    echo "commit=$SHA"
    echo "started=$STARTED"
    echo "finished=$(date -Is)"
    echo "log=$LOG"
  } >"$STATE_DIR/last-run"
  if [[ "$result" == ok ]]; then
    cp "$STATE_DIR/last-run" "$STATE_DIR/last-success"
    echo "== nightly run OK at $SHA"
  else
    echo "== nightly run FAILED at step: $STEP (exit $code). The previous release keeps running."
    [[ "$code" != 0 ]] || code=1
  fi
  # Let tee write the last lines to the log before the job ends (systemd would kill it).
  exec >&- 2>&-
  wait "$TEE_PID" 2>/dev/null || true
  exit "$code"
}

# On one line: after `main` returns, bash would read the next line of this file at its old
# offset, and `git reset --hard` may have replaced the file meanwhile.
main "$@"; exit $?
