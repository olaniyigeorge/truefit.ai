#!/usr/bin/env bash
# =============================================================================
# setup-local-composed.sh - One-shot local setup for TrueFit.ai
#
# Installs the toolchain and services, runs `make setup`, downloads the free
# "composed" voice pipeline components, and points the backend .env at them:
#
#   * Ollama + a 7B-class tool-calling model   (~4.7 GB)
#   * faster-whisper base.en STT model         (~150 MB)
#   * Piper en_US-lessac-medium voice          (~63 MB)
#
# Idempotent: safe to re-run. Skips anything already present.
#
# Usage:
#   bash scripts/setup-local-composed.sh
#
# Optional environment overrides:
#   OLLAMA_MODEL=qwen2.5:7b     # any tool-calling model in the Ollama registry
#   SKIP_MODELS=1               # skip the Ollama/Whisper/Piper downloads
#   SKIP_BREW=1                 # assume the toolchain is already installed
# =============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
NC=$'\033[0m'

log()     { echo -e "${BLUE}[setup]${NC} $1"; }
success() { echo -e "${GREEN}[ok]${NC}    $1"; }
warn()    { echo -e "${YELLOW}[warn]${NC}  $1"; }
die()     { echo -e "${RED}[error]${NC} $1" >&2; exit 1; }

# -----------------------------------------------------------------------------
# 0. Sanity: macOS + Homebrew + free disk
# -----------------------------------------------------------------------------
if [ "$(uname -s)" != "Darwin" ]; then
  die "This script targets macOS. On Linux, install the equivalents with your package manager."
fi

if ! command -v brew >/dev/null 2>&1; then
  if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [ -x /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
  else
    die "Homebrew not found. Install it from https://brew.sh and re-run."
  fi
fi

FREE_GB="$(df -g "$ROOT_DIR" | awk 'NR==2 {print $4}')"
if [ "${FREE_GB:-0}" -lt 12 ]; then
  warn "Only ${FREE_GB}GB free on this volume. The composed models need ~6GB."
fi

# -----------------------------------------------------------------------------
# 1. Toolchain
# -----------------------------------------------------------------------------
if [ "${SKIP_BREW:-0}" != "1" ]; then
  NEED=()
  need_pkg() { # need_pkg <formula> [command-to-test...]
    local pkg="$1"; shift
    local c
    for c in "$@"; do
      command -v "$c" >/dev/null 2>&1 && return 0
    done
    brew list --versions "$pkg" >/dev/null 2>&1 && return 0
    NEED+=("$pkg")
  }

  need_pkg python@3.12 python3.12
  need_pkg node node
  need_pkg pnpm pnpm
  need_pkg postgresql@16 psql
  need_pkg redis redis-server
  need_pkg ruff ruff
  need_pkg ollama ollama
  command -v git  >/dev/null 2>&1 || NEED+=("git")
  command -v make >/dev/null 2>&1 || NEED+=("make")

  if [ "${#NEED[@]}" -gt 0 ]; then
    log "Installing Homebrew formulae: ${NEED[*]}"
    brew install "${NEED[@]}"
  else
    success "Toolchain already installed"
  fi
fi

# Versioned formulae are keg-only: put their binaries on PATH for this script.
PG_PREFIX="$(brew --prefix postgresql@16 2>/dev/null || true)"
[ -n "$PG_PREFIX" ] && export PATH="$PG_PREFIX/bin:$PATH"

PY_PREFIX="$(brew --prefix python@3.12 2>/dev/null || true)"
if [ -n "$PY_PREFIX" ]; then
  # libexec/bin/python3 is the unversioned shim that `make setup` calls.
  export PATH="$PY_PREFIX/libexec/bin:$PY_PREFIX/bin:$PATH"
fi

for c in git make python3 node pnpm psql createdb pg_isready redis-server redis-cli ruff ollama; do
  command -v "$c" >/dev/null 2>&1 || die "$c not found on PATH; install it and re-run."
done

python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' \
  || die "python3 is $(python3 -V 2>&1); this project needs Python 3.11+."

log "python $(python3 -V 2>&1 | awk '{print $2}'), node $(node -v), pnpm $(pnpm -v)"

# -----------------------------------------------------------------------------
# 2. Services: PostgreSQL, Redis, Ollama
# -----------------------------------------------------------------------------
log "Starting services..."
if ! pg_isready -q 2>/dev/null; then
  brew services start postgresql@16 >/dev/null 2>&1 || warn "Could not start postgresql@16 via brew services"
fi
brew services start redis >/dev/null 2>&1 || warn "Could not start redis via brew services"
if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  brew services start ollama >/dev/null 2>&1 || warn "Ollama is not Homebrew-managed; will start it later if needed"
fi

for _ in $(seq 1 30); do [ "$(redis-cli ping 2>/dev/null || true)" = "PONG" ] && break; sleep 1; done
[ "$(redis-cli ping 2>/dev/null || true)" = "PONG" ] || die "Redis is not responding."
success "Redis is up"

# -----------------------------------------------------------------------------
# PostgreSQL: use whatever server is already running if we can log in without a
# password prompt; otherwise create a private cluster (port 5433) with trust auth.
# This handles Postgres.app, Docker, and other Homebrew versions that own 5432.
# -----------------------------------------------------------------------------
PG_PORT=5432
PG_USER=""
DB_READY=0

probe_pg() { # probe_pg <user> [port]
  local user="$1" port="${2:-5432}"
  PGCONNECT_TIMEOUT=3 psql -w -h 127.0.0.1 -p "$port" -U "$user" -d postgres \
    -tAc "SELECT 1" >/dev/null 2>&1
}

for _ in $(seq 1 30); do pg_isready -q 2>/dev/null && break; sleep 1; done

if pg_isready -q 2>/dev/null; then
  for candidate in "$(whoami)" postgres; do
    if probe_pg "$candidate" 5432; then
      PG_USER="$candidate"
      DB_READY=1
      break
    fi
  done
fi

if [ "$DB_READY" -eq 1 ]; then
  success "Using existing PostgreSQL on port 5432 (user $PG_USER)"
else
  warn "No password-free PostgreSQL login found; creating a private cluster on port 5433"
  PG_PORT=5433
  PG_USER=postgres
  PGDATA_DIR="$HOME/.truefit-pgdata"

  while lsof -nP -iTCP:"$PG_PORT" -sTCP:LISTEN >/dev/null 2>&1; do
    PG_PORT=$((PG_PORT + 1))
  done

  if ! command -v initdb >/dev/null 2>&1 || ! command -v pg_ctl >/dev/null 2>&1; then
    log "Installing postgresql@16 for server binaries"
    brew install postgresql@16
    export PATH="$(brew --prefix postgresql@16)/bin:$PATH"
  fi

  if [ ! -f "$PGDATA_DIR/PG_VERSION" ]; then
    initdb -D "$PGDATA_DIR" --auth=trust -U postgres >/dev/null
  fi

  if ! pg_ctl -D "$PGDATA_DIR" status >/dev/null 2>&1; then
    pg_ctl -D "$PGDATA_DIR" -o "-p $PG_PORT" -l "$PGDATA_DIR/server.log" start >/dev/null
  fi

  for _ in $(seq 1 30); do
    pg_isready -h 127.0.0.1 -p "$PG_PORT" -q && break
    sleep 1
  done
  pg_isready -h 127.0.0.1 -p "$PG_PORT" -q \
    || die "Private PostgreSQL failed to start; see $PGDATA_DIR/server.log"
  success "Private PostgreSQL running on port $PG_PORT (data: $PGDATA_DIR)"
fi

DB_URL="postgresql+asyncpg://${PG_USER}@127.0.0.1:${PG_PORT}/truefit_db"

if PGCONNECT_TIMEOUT=3 psql -w -h 127.0.0.1 -p "$PG_PORT" -U "$PG_USER" -d postgres \
     -tAc "SELECT 1 FROM pg_database WHERE datname='truefit_db'" 2>/dev/null | grep -q 1; then
  success "Database truefit_db already exists"
else
  PGCONNECT_TIMEOUT=3 createdb -w -h 127.0.0.1 -p "$PG_PORT" -U "$PG_USER" truefit_db
  success "Created database truefit_db"
fi

# -----------------------------------------------------------------------------
# 3. Project dependencies (backend venv + soro[all] + frontend)
# -----------------------------------------------------------------------------
log "Running make setup (this installs aiortc, faster-whisper, piper, ...)"
make setup
success "make setup finished"

VENV="$ROOT_DIR/examples/truefit/backend/.venv"
[ -x "$VENV/bin/python" ] || die "Backend venv was not created at $VENV"

# -----------------------------------------------------------------------------
# 4. Composed pipeline downloads
# -----------------------------------------------------------------------------
# Declared outside the SKIP_MODELS branch: the .env step below still needs them.
VOICE_DIR="$ROOT_DIR/examples/truefit/backend/models/piper"
VOICE_NAME="en_US-lessac-medium"
VOICE_PATH="$VOICE_DIR/$VOICE_NAME.onnx"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:7b}"

if [ "${SKIP_MODELS:-0}" = "1" ]; then
  warn "SKIP_MODELS=1: skipping Ollama, Whisper and Piper downloads"
else

  # --- Piper voice -----------------------------------------------------------
  mkdir -p "$VOICE_DIR"

  log "Downloading Piper voice $VOICE_NAME"
  for ext in ".onnx" ".onnx.json"; do
    if [ ! -s "$VOICE_DIR/$VOICE_NAME$ext" ]; then
      curl -fL --retry 3 --progress-bar \
        -o "$VOICE_DIR/$VOICE_NAME$ext" \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/$VOICE_NAME$ext"
    fi
  done
  success "Piper voice ready at $VOICE_PATH"

  # --- faster-whisper model --------------------------------------------------
  log "Downloading/caching faster-whisper base.en (~150MB on first run)"
  "$VENV/bin/python" - <<'PY'
from faster_whisper import WhisperModel
WhisperModel("base.en", device="cpu", compute_type="int8")
print("faster-whisper base.en ready")
PY
  success "Whisper model ready"

  # --- Ollama model ----------------------------------------------------------
  if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    warn "Ollama service not responding; starting 'ollama serve' in the background"
    nohup ollama serve >/tmp/ollama.log 2>&1 &
    for _ in $(seq 1 60); do
      curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
      sleep 2
    done
  fi
  curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1 \
    || die "Ollama is not responding on port 11434. Check /tmp/ollama.log."

  log "Pulling Ollama model $OLLAMA_MODEL (~4.7GB for 7B)"
  ollama pull "$OLLAMA_MODEL"
  success "Ollama model $OLLAMA_MODEL ready"

fi

# -----------------------------------------------------------------------------
# 5. Point the backend .env at local services and the composed pipeline
# -----------------------------------------------------------------------------
ENV_FILE="$ROOT_DIR/examples/truefit/backend/.env"
[ -f "$ENV_FILE" ] || die "Missing $ENV_FILE (make setup should have copied it)."

log "Updating backend .env"
"$VENV/bin/python" - "$ENV_FILE" "$DB_URL" "$VOICE_PATH" "$OLLAMA_MODEL" <<'PY'
import pathlib
import re
import secrets
import sys

env_path, db_url_new, voice_path, ollama_model = sys.argv[1:5]
p = pathlib.Path(env_path)
text = p.read_text()


def get(key: str) -> str:
    m = re.search(rf"^{re.escape(key)}=(.*)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def set_value(key: str, value: str, force: bool = False) -> None:
    global text
    if get(key) and not force:
        return
    line = f"{key}={value}"
    if re.search(rf"^{re.escape(key)}=.*$", text, re.MULTILINE):
        text = re.sub(rf"^{re.escape(key)}=.*$", line, text, count=1, flags=re.MULTILINE)
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"


def bare(key: str) -> str:
    return get(key).split("#", 1)[0].strip()


# Generate secrets only where the example placeholders are still present.
if bare("APP_SECRET_KEY") in ("", "change_me_super_secret"):
    set_value("APP_SECRET_KEY", secrets.token_urlsafe(32), force=True)
if bare("WEBRTC_TOKEN_SECRET") in ("", "change_me_webrtc_secret"):
    set_value("WEBRTC_TOKEN_SECRET", secrets.token_urlsafe(32), force=True)

db_url = bare("DATABASE_URL")
if not db_url or db_url.startswith("postgresql+asyncpg://user:password"):
    set_value("DATABASE_URL", db_url_new, force=True)

# Use the free local pipeline by default. Set LLM_PRIMARY_PROVIDER=gemini in
# this file (and add GEMINI_API_KEY) to switch back.
set_value("LLM_PRIMARY_PROVIDER", "composed", force=True)
set_value("COMPOSED_LLM_BASE_URL", "http://127.0.0.1:11434/v1", force=True)
set_value("COMPOSED_LLM_MODEL", ollama_model, force=True)
set_value("COMPOSED_STT_MODEL", "base.en", force=True)
set_value("COMPOSED_TTS_VOICE", voice_path, force=True)

p.write_text(text)
print(f"updated {env_path}")
PY
success "Backend configured for the composed pipeline"

# -----------------------------------------------------------------------------
# 6. Database migrations + verification
# -----------------------------------------------------------------------------
log "Applying Alembic migrations"
if (cd "$ROOT_DIR/examples/truefit/backend" && "$VENV/bin/alembic" upgrade head); then
  success "Migrations applied"
else
  warn "alembic upgrade failed. The app also creates tables on startup; see docs/architecture.md."
fi

log "Verifying composed-pipeline imports"
"$VENV/bin/python" - <<'PY'
import importlib
for name in ("faster_whisper", "piper", "onnxruntime", "numpy", "httpx", "soro"):
    importlib.import_module(name)
print("composed Python dependencies import OK")
PY

if [ "${SKIP_MODELS:-0}" != "1" ]; then
  curl -sf http://127.0.0.1:11434/v1/models >/dev/null \
    && success "Ollama OpenAI-compatible API responds at http://127.0.0.1:11434/v1"
fi

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
echo
echo -e "${GREEN}==============================================${NC}"
echo -e "${GREEN}  Local setup complete${NC}"
echo -e "${GREEN}==============================================${NC}"
echo
echo "  Backend provider : composed (free, local)"
echo "  LLM              : ${OLLAMA_MODEL:-qwen2.5:7b} via Ollama"
echo "  STT              : faster-whisper base.en"
echo "  TTS              : ${VOICE_PATH:-Piper voice}"
echo "  Database         : truefit_db"
echo
echo "  Run the app:   make dev"
echo "  Backend docs:  http://localhost:8000/api/docs"
echo "  Frontend:      http://localhost:5173"
echo
echo -e "${YELLOW}Still manual:${NC} Firebase keys in examples/truefit/frontend/.env"
echo "  (VITE_FIREBASE_*) are required for the login flow."
echo
