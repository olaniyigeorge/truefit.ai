#!/bin/bash
# =============================================================================
# setup-gcp.sh — TrueFit GCP Infrastructure Provisioning Script
# Runs on your LOCAL machine
# Usage: bash setup-gcp.sh
# Requires: gcloud CLI installed and authenticated
# =============================================================================

set -euo pipefail

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
# ── CONFIGURATION — edit before running ───────────────────────────────────────
# =============================================================================
PROJECT_ID="truefit-490409"        # <-- change this
VM_NAME="truefit-engine"
ZONE="us-central1-b"
MACHINE_TYPE="e2-medium"
DISK_SIZE="20GB"
IMAGE_FAMILY="ubuntu-2204-lts"
IMAGE_PROJECT="ubuntu-os-cloud"
REPO_URL="https://github.com/olaniyigeorge/truefit.ai.git" 

# =============================================================================
# ── STEP 1: Verify gcloud is set up ───────────────────────────────────────────
# =============================================================================
log "Checking gcloud setup..."

if ! command -v gcloud &>/dev/null; then
    error "gcloud CLI not found. Install it: https://cloud.google.com/sdk/docs/install"
fi

gcloud config set project "$PROJECT_ID"
success "Using project: $PROJECT_ID"

# =============================================================================
# ── STEP 2: Enable required GCP APIs ──────────────────────────────────────────
# =============================================================================
log "Enabling required GCP APIs..."

gcloud services enable compute.googleapis.com --quiet
success "Compute Engine API enabled"

# =============================================================================
# ── STEP 3: Create Firewall Rules ─────────────────────────────────────────────
# =============================================================================
log "Creating firewall rules..."

# Allow HTTP (port 80)
if ! gcloud compute firewall-rules describe allow-http --quiet &>/dev/null; then
    gcloud compute firewall-rules create allow-http \
        --allow tcp:80 \
        --target-tags=http-server \
        --description="Allow HTTP traffic" \
        --quiet
    success "Firewall rule: allow-http created"
else
    warn "Firewall rule allow-http already exists — skipping"
fi

# Allow HTTPS (port 443)
if ! gcloud compute firewall-rules describe allow-https --quiet &>/dev/null; then
    gcloud compute firewall-rules create allow-https \
        --allow tcp:443 \
        --target-tags=https-server \
        --description="Allow HTTPS traffic" \
        --quiet
    success "Firewall rule: allow-https created"
else
    warn "Firewall rule allow-https already exists — skipping"
fi

# Allow FastAPI direct access (port 8000) — for debugging
if ! gcloud compute firewall-rules describe allow-truefit-api --quiet &>/dev/null; then
    gcloud compute firewall-rules create allow-truefit-api \
        --allow tcp:8000 \
        --target-tags=http-server \
        --description="Allow direct FastAPI access on port 8000" \
        --quiet
    success "Firewall rule: allow-truefit-api created"
else
    warn "Firewall rule allow-truefit-api already exists — skipping"
fi

# =============================================================================
# ── STEP 4: Create the VM ─────────────────────────────────────────────────────
# =============================================================================
log "Creating VM instance: $VM_NAME..."

if gcloud compute instances describe "$VM_NAME" --zone="$ZONE" --quiet &>/dev/null; then
    warn "VM $VM_NAME already exists — skipping creation"
else
    gcloud compute instances create "$VM_NAME" \
        --zone="$ZONE" \
        --machine-type="$MACHINE_TYPE" \
        --image-family="$IMAGE_FAMILY" \
        --image-project="$IMAGE_PROJECT" \
        --boot-disk-size="$DISK_SIZE" \
        --tags=http-server,https-server \
        --metadata=startup-script='#!/bin/bash
            apt-get update -qq
            apt-get install -y -qq git' \
        --quiet

    success "VM $VM_NAME created in $ZONE"
fi

# =============================================================================
# ── STEP 5: Reserve a Static External IP ──────────────────────────────────────
# =============================================================================
log "Reserving static external IP..."

STATIC_IP_NAME="truefit-static-ip"

if ! gcloud compute addresses describe "$STATIC_IP_NAME" --region="${ZONE%-*}" --quiet &>/dev/null; then
    gcloud compute addresses create "$STATIC_IP_NAME" \
        --region="${ZONE%-*}" \
        --quiet
    success "Static IP reserved: $STATIC_IP_NAME"
else
    warn "Static IP $STATIC_IP_NAME already exists — skipping"
fi

STATIC_IP=$(gcloud compute addresses describe "$STATIC_IP_NAME" \
    --region="${ZONE%-*}" \
    --format="get(address)")

# Assign static IP to VM
gcloud compute instances delete-access-config "$VM_NAME" \
    --zone="$ZONE" \
    --access-config-name="External NAT" \
    --quiet 2>/dev/null || true

gcloud compute instances add-access-config "$VM_NAME" \
    --zone="$ZONE" \
    --access-config-name="External NAT" \
    --address="$STATIC_IP" \
    --quiet

success "Static IP $STATIC_IP assigned to $VM_NAME"

# =============================================================================
# ── STEP 6: Copy deploy.sh to VM and run it ───────────────────────────────────
# =============================================================================
log "Waiting for VM to be ready..."
sleep 15

log "Copying deploy.sh to VM..."

# Update REPO_URL in deploy.sh before copying
sed "s|https://github.com/YOUR_ORG/truefit.ai.git|${REPO_URL}|g" deploy.sh > /tmp/deploy.sh

gcloud compute scp /tmp/deploy.sh "${VM_NAME}:~/deploy.sh" \
    --zone="$ZONE" \
    --quiet

log "Running deploy.sh on VM..."

gcloud compute ssh "$VM_NAME" \
    --zone="$ZONE" \
    --command="chmod +x ~/deploy.sh && bash ~/deploy.sh" \
    --quiet

# =============================================================================
# ── Done ──────────────────────────────────────────────────────────────────────
# =============================================================================
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  TrueFit GCP setup complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  🖥️  VM:         $VM_NAME ($ZONE)"
echo -e "  🌐 Frontend:   http://${STATIC_IP}"
echo -e "  🔌 API:        http://${STATIC_IP}/api"
echo -e "  📖 API Docs:   http://${STATIC_IP}:8000/docs"
echo ""
echo -e "SSH into VM:"
echo -e "  gcloud compute ssh $VM_NAME --zone=$ZONE"
echo ""