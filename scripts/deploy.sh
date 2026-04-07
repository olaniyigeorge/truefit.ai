#!/bin/bash
# =============================================================================
# deploy.sh - TrueFit Full Stack Deployment Script
# Runs ON the GCP Compute Engine VM
# Usage: bash deploy.sh
# =============================================================================

set -euo pipefail

# ─── Colours ────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()    { echo -e "${BLUE}[INFO]${NC}  $1"; }
success(){ echo -e "${GREEN}[OK]${NC}    $1"; }
warn()   { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error()  { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# =============================================================================
# ── CONFIGURATION ─────
# =============================================================================
REPO_URL="https://github.com/olaniyigeorge/truefit.ai.git"
APP_DIR="$HOME/truefit.ai"
FRONTEND_DIR="$APP_DIR/apps/frontend"
BACKEND_DIR="$APP_DIR/apps/backend"
BACKEND_MODULE="src.truefit_api.main:app"
BACKEND_PORT=8000
VM_USER=$(whoami)
NGINX_CONF="/etc/nginx/sites-available/truefit"
SERVICE_NAME="truefit-api"

# =============================================================================
# ── STEP 1: System Dependencies ─────
# =============================================================================
log "Installing system dependencies..."

export DEBIAN_FRONTEND=noninteractive

sudo apt-get update -qq
sudo apt-get install -y -qq \
    git curl wget build-essential \
    python3 python3-pip python3-venv python3-dev \
    nginx \
    postgresql-client \
    libpq-dev \
    redis-server

# Node.js 20.x
if ! command -v node &>/dev/null; then
    log "Installing Node.js 20..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - > /dev/null
    sudo apt-get install -y -qq nodejs
fi

# Enable and start Redis
sudo systemctl enable redis-server > /dev/null
sudo systemctl start redis-server

if sudo systemctl is-active --quiet redis-server; then
    success "Redis is running"
else
    warn "Redis failed to start - check: sudo systemctl status redis-server"
fi

success "System dependencies ready  (node $(node -v), python $(python3 --version))"

# =============================================================================
# ── STEP 2: Clone or Update Repo ────
# =============================================================================
if [ -d "$APP_DIR/.git" ]; then
    log "Repo exists - pulling latest changes..."
    git -C "$APP_DIR" pull origin main
else
    log "Cloning repo..."
    git clone "$REPO_URL" "$APP_DIR"
fi

success "Repo up to date"

# =============================================================================
# ── STEP 3: Backend - Python venv + dependencies ──
# =============================================================================
log "Setting up Python virtual environment..."

cd "$BACKEND_DIR"

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate

pip install --upgrade pip -q

if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt -q
elif [ -f "pyproject.toml" ]; then
    pip install . -q
else
    error "No requirements.txt or pyproject.toml found in $BACKEND_DIR"
fi

pip install uvicorn -q

deactivate
success "Backend dependencies installed"

# =============================================================================
# ── STEP 4: Backend - .env file ─────
# =============================================================================
if [ ! -f "$BACKEND_DIR/.env" ]; then
    if [ -f "$BACKEND_DIR/.env.example" ]; then
        warn ".env not found - copying from .env.example. Fill in real values!"
        cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
    else
        warn "No .env or .env.example found. Make sure environment variables are set."
    fi
else
    success ".env file found"
fi

# =============================================================================
# ── STEP 5: Backend - systemd service ─
# =============================================================================
log "Configuring systemd service for FastAPI..."

sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=TrueFit FastAPI Backend
After=network.target

[Service]
User=${VM_USER}
WorkingDirectory=${BACKEND_DIR}
EnvironmentFile=${BACKEND_DIR}/.env
ExecStart=${BACKEND_DIR}/venv/bin/uvicorn ${BACKEND_MODULE} --host 0.0.0.0 --port ${BACKEND_PORT} --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME" > /dev/null
sudo systemctl restart "$SERVICE_NAME"

sleep 2

if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    success "FastAPI service is running"
else
    error "FastAPI service failed to start. Run: sudo journalctl -u $SERVICE_NAME -n 50"
fi

# =============================================================================
# ── STEP 6: Frontend - install + build 
# =============================================================================
log "Building React frontend..."

cd "$FRONTEND_DIR"
npm install --silent
npm run build

if [ -d "$FRONTEND_DIR/dist" ]; then
    FRONTEND_BUILD="$FRONTEND_DIR/dist"
elif [ -d "$FRONTEND_DIR/build" ]; then
    FRONTEND_BUILD="$FRONTEND_DIR/build"
else
    error "Frontend build output not found (expected dist/ or build/)"
fi

success "Frontend built -> $FRONTEND_BUILD"

# =============================================================================
# ── STEP 7: Nginx - serve frontend + proxy API ────
# =============================================================================
log "Configuring Nginx..."

EXTERNAL_IP=$(curl -s ifconfig.me)

sudo tee "$NGINX_CONF" > /dev/null <<EOF
server {
    listen 80;
    server_name ${EXTERNAL_IP} _;

    root ${FRONTEND_BUILD};
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:${BACKEND_PORT}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:${BACKEND_PORT}/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_read_timeout 3600s;
    }
}
EOF

sudo ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/truefit
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx
success "Nginx configured and restarted"

# =============================================================================
# ── STEP 8: Health Checks ─────
# =============================================================================
log "Running health checks..."
sleep 2

if redis-cli ping | grep -q "PONG"; then
    success "Redis is responding"
else
    warn "Redis not responding - check: sudo systemctl status redis-server"
fi

if curl -s -o /dev/null -w "%{http_code}" http://localhost:${BACKEND_PORT} | grep -qE "^(200|404|422)$"; then
    success "Backend responding on port ${BACKEND_PORT}"
else
    warn "Backend not responding - check: sudo journalctl -u ${SERVICE_NAME} -n 50"
fi

if curl -s -o /dev/null -w "%{http_code}" http://localhost:80 | grep -qE "^(200|301|302)$"; then
    success "Nginx serving on port 80"
else
    warn "Nginx check failed - check: sudo nginx -t"
fi

# =============================================================================
# ── Done 
# =============================================================================
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  TrueFit deployed successfully!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  🌐 Frontend:   http://${EXTERNAL_IP}"
echo -e "  🔌 API:        http://${EXTERNAL_IP}/api"
echo -e "  📖 API Docs:   http://${EXTERNAL_IP}:${BACKEND_PORT}/docs"
echo -e "  🔁 WebSockets: ws://${EXTERNAL_IP}/ws"
echo ""
echo -e "Useful commands:"
echo -e "  sudo systemctl status ${SERVICE_NAME}    # API status"
echo -e "  sudo journalctl -u ${SERVICE_NAME} -f    # API logs"
echo -e "  sudo systemctl status nginx              # Nginx status"
echo ""