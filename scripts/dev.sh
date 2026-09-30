#!/usr/bin/env bash
# Spin up the backend (FastAPI/uvicorn) and frontend (Vite) together in dev mode.
# Bootstraps the backend venv and frontend deps on first run if missing.
set -euo pipefail
set -m # job control: each backgrounded pipeline below becomes its own process group,
       # so we can kill uvicorn's/vite's child processes on shutdown, not just the shell wrapping them.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/apps/backend"
FRONTEND_DIR="$ROOT_DIR/apps/frontend"
VENV_DIR="$BACKEND_DIR/.venv"

# Real escape characters ($'...'), not the text \033. The backend and frontend lines
# are prefixed through sed, which would read \0 as "the matched text" and print "33[0;32m".
GREEN=$'\033[0;32m'
CYAN=$'\033[0;36m'
YELLOW=$'\033[1;33m'
NC=$'\033[0m'

log() { echo -e "${YELLOW}[dev]${NC} $1"; }

# --- Backend bootstrap ---
if [ ! -d "$VENV_DIR" ]; then
  log "No backend venv found, creating one..."
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install --upgrade pip -q
  # run from the backend dir: requirements.txt has a relative path to packages/soro
  (cd "$BACKEND_DIR" && "$VENV_DIR/bin/pip" install -r requirements.txt)
fi

if [ ! -f "$BACKEND_DIR/.env" ]; then
  log "No apps/backend/.env found, copying from env.example"
  cp "$BACKEND_DIR/env.example" "$BACKEND_DIR/.env"
fi

# --- Frontend bootstrap ---
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  log "No frontend node_modules found, running pnpm install..."
  (cd "$FRONTEND_DIR" && pnpm install)
fi

if [ ! -f "$FRONTEND_DIR/.env" ]; then
  log "No apps/frontend/.env found, copying from env.example"
  cp "$FRONTEND_DIR/env.example" "$FRONTEND_DIR/.env"
fi

# --- Run both, prefixed, and kill both (and their child processes) on exit ---
pids=()
cleaned_up=0

cleanup() {
  [ "$cleaned_up" -eq 1 ] && return
  cleaned_up=1
  log "Shutting down..."
  for pid in "${pids[@]}"; do
    # Negative PID targets the whole process group (uvicorn's reloader worker,
    # vite's underlying node process, etc.), not just the immediate shell.
    kill -TERM -- "-$pid" 2>/dev/null || true
  done
  sleep 1
  for pid in "${pids[@]}"; do
    kill -0 -- "-$pid" 2>/dev/null && kill -KILL -- "-$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(
  cd "$BACKEND_DIR"
  exec "$VENV_DIR/bin/python" run.py 2>&1 | sed -u -e "s/^/${GREEN}[backend]${NC} /"
) &
pids+=($!)

(
  cd "$FRONTEND_DIR"
  exec pnpm dev 2>&1 | sed -u -e "s/^/${CYAN}[frontend]${NC} /"
) &
pids+=($!)

log "Backend running via uvicorn (http://localhost:8000) and frontend via Vite (http://localhost:5173)."
log "Press Ctrl+C to stop both."

wait -n "${pids[@]}"
