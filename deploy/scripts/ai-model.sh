#!/usr/bin/env bash
# The local AI model servers for development on a Mac, run natively with Metal (WP-037 session 2;
# product owner, 2026-11-04). Never in Docker: a large model in a container on a developer Mac
# starves everything else. CI never runs this; it uses the recorded fake.
#
#   deploy/scripts/ai-model.sh dev      Qwen3-4B Q4_K_M (~2.5 GB) for daily work and tests
#   deploy/scripts/ai-model.sh demo     Qwen3-14B Q4_K_M (~9 GB) for demos, with the lanes paused
#   deploy/scripts/ai-model.sh stop     stop both servers; the API goes back to the recorded fake
#   deploy/scripts/ai-model.sh status   what runs, and what backend/.env points at
#
# Two llama.cpp servers (one model each): chat on 127.0.0.1:8081, embeddings (bge-m3 Q8_0, ~0.6 GB)
# on 127.0.0.1:8082. Models download on first use into llama.cpp's cache (Hugging Face, the
# official Qwen GGUF files; bge-m3 converted by gpustack). Only the SUPPORTX_AI_* lines of
# backend/.env change; the file is copied to backend/.env.before-ai once, the first time.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${SUPPORTX_AI_ENV_FILE:-$ROOT/backend/.env}"
STATE="${SUPPORTX_AI_STATE:-$HOME/.cache/supportx/ai}"
CHAT_PORT="${SUPPORTX_AI_CHAT_PORT:-8081}"
EMBED_PORT="${SUPPORTX_AI_EMBED_PORT:-8082}"
DEV_REPO="Qwen/Qwen3-4B-GGUF:Q4_K_M"
DEMO_REPO="Qwen/Qwen3-14B-GGUF:Q4_K_M"
EMBED_REPO="gpustack/bge-m3-GGUF:Q8_0"
# The 14B model needs about 9 GB plus its context; below this much free memory it is refused.
DEMO_MIN_FREE_GB="${SUPPORTX_AI_DEMO_MIN_FREE_GB:-12}"

mkdir -p "$STATE"

say() { printf 'ai-model: %s\n' "$*"; }

need_server() {
  if ! command -v llama-server >/dev/null 2>&1; then
    say "llama-server is not installed. Install it with: brew install llama.cpp"
    exit 1
  fi
}

# Free memory in whole GB: free, inactive and speculative pages (what macOS can hand out now).
free_gb() {
  vm_stat | awk '/page size of/ {size=$8} /Pages (free|inactive|speculative)/ {gsub("\\.","",$NF); n+=$NF} END {printf "%d", n*size/1073741824}'
}

pid_of() { cat "$STATE/$1.pid" 2>/dev/null || true; }
running() { local pid; pid="$(pid_of "$1")"; [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; }

stop_server() {
  local pid
  if running "$1"; then
    pid="$(pid_of "$1")"
    kill "$pid"
    for _ in $(seq 1 30); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    say "stopped $1"
  fi
  rm -f "$STATE/$1.pid" "$STATE/$1.alias"
}

# start_server <name> <repo> <alias> <port> [extra llama-server arguments...]
start_server() {
  local name=$1 repo=$2 alias=$3 port=$4
  shift 4
  if running "$name" && [ "$(cat "$STATE/$name.alias" 2>/dev/null)" = "$alias" ]; then
    say "$name already serves $alias on :$port"
    return
  fi
  stop_server "$name"
  say "starting $alias on 127.0.0.1:$port (the first start downloads the model; log: $STATE/$name.log)"
  nohup llama-server -hf "$repo" --alias "$alias" --host 127.0.0.1 --port "$port" \
    --n-gpu-layers 99 "$@" >"$STATE/$name.log" 2>&1 &
  echo $! >"$STATE/$name.pid"
  echo "$alias" >"$STATE/$name.alias"
  # Up to 30 minutes: a first download on a slow line.
  for _ in $(seq 1 900); do
    if curl -sf "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
      say "$alias is ready on :$port"
      return
    fi
    if ! running "$name"; then
      say "$name stopped while starting; the end of its log:"
      tail -n 20 "$STATE/$name.log" >&2
      exit 1
    fi
    sleep 2
  done
  say "$alias did not answer within 30 minutes; see $STATE/$name.log"
  exit 1
}

# Other work on this Mac: lane sessions, the API, test runners and the browser tests.
warn_busy() {
  local busy
  busy="$(pgrep -f 'claude|uvicorn app.main|pytest|vitest|playwright' 2>/dev/null | wc -l | tr -d ' ')"
  if [ "${busy:-0}" -gt 0 ]; then
    say "warning: $busy other processes look like lane work (Claude sessions, the API, tests)."
    say "         The 14B model is meant for demos with the lanes paused."
  fi
}

# Point backend/.env at the servers (or back at the fake); only the SUPPORTX_AI_* lines change.
set_env() {
  if [ ! -f "$ENV_FILE" ]; then
    say "backend/.env does not exist yet: run make backend-env first, then this again."
    exit 1
  fi
  [ -f "$ENV_FILE.before-ai" ] || cp "$ENV_FILE" "$ENV_FILE.before-ai"
  local key value tmp
  tmp="$(mktemp)"
  cp "$ENV_FILE" "$tmp"
  while [ $# -gt 0 ]; do
    key=$1 value=$2
    shift 2
    if grep -q "^$key=" "$tmp"; then
      awk -v k="$key" -v v="$value" 'index($0, k"=")==1 {print k"="v; next} {print}' "$tmp" >"$tmp.next"
      mv "$tmp.next" "$tmp"
    else
      printf '%s=%s\n' "$key" "$value" >>"$tmp"
    fi
  done
  cat "$tmp" >"$ENV_FILE"
  rm -f "$tmp"
  say "backend/.env updated (restart the API to pick it up)"
}

use_model() {
  set_env SUPPORTX_AI_PROVIDER openai_compatible \
    SUPPORTX_AI_BASE_URL "http://127.0.0.1:$CHAT_PORT/v1" \
    SUPPORTX_AI_MODEL "$1" \
    SUPPORTX_AI_EMBEDDING_BASE_URL "http://127.0.0.1:$EMBED_PORT/v1" \
    SUPPORTX_AI_EMBEDDING_MODEL bge-m3
}

start_embeddings() {
  start_server embed "$EMBED_REPO" bge-m3 "$EMBED_PORT" --embedding --pooling cls --ctx-size 8192
}

# Chat: thinking is kept apart from the answer (reasoning_content), 8k context.
CHAT_ARGS=(--ctx-size 8192 --reasoning-format deepseek --jinja)

case "${1:-status}" in
  dev)
    need_server
    start_server chat "$DEV_REPO" qwen3-4b "$CHAT_PORT" "${CHAT_ARGS[@]}"
    start_embeddings
    use_model qwen3-4b
    ;;
  demo)
    need_server
    warn_busy
    stop_server chat
    free="$(free_gb)"
    if [ "$free" -lt "$DEMO_MIN_FREE_GB" ]; then
      say "only $free GB free; the 14B model needs $DEMO_MIN_FREE_GB GB. Pause the lanes, close"
      say "large apps and try again. Starting the 4B model again meanwhile."
      start_server chat "$DEV_REPO" qwen3-4b "$CHAT_PORT" "${CHAT_ARGS[@]}"
      use_model qwen3-4b
      exit 1
    fi
    start_server chat "$DEMO_REPO" qwen3-14b "$CHAT_PORT" "${CHAT_ARGS[@]}"
    start_embeddings
    use_model qwen3-14b
    say "demo model on. Back to the light one afterwards: make ai-dev-model"
    ;;
  stop)
    stop_server chat
    stop_server embed
    if [ -f "$ENV_FILE" ]; then set_env SUPPORTX_AI_PROVIDER fake; fi
    ;;
  status)
    for name in chat embed; do
      if running "$name"; then say "$name: $(cat "$STATE/$name.alias") (pid $(pid_of "$name"))"; else say "$name: stopped"; fi
    done
    say "free memory: $(free_gb) GB"
    if [ -f "$ENV_FILE" ]; then grep '^SUPPORTX_AI_' "$ENV_FILE" || say "backend/.env: no AI settings (the recorded fake)"; fi
    ;;
  *)
    say "usage: $0 dev|demo|stop|status"
    exit 2
    ;;
esac
