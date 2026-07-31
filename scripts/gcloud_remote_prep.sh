#!/usr/bin/env bash
# Fix VM ownership so gcloud scp can overwrite app files (root-owned files block deploy).
# Usage: source scripts/gcloud_remote_prep.sh  (after gcloud_auth_from_env.sh)
set -euo pipefail

PROJECT="${GCP_PROJECT:-sritej-trading-algo-2026}"
INSTANCE="${GCP_INSTANCE:-sritej-trading}"
ZONE="${GCP_ZONE:-asia-south1-c}"
REMOTE_USER="${GCP_REMOTE_USER:-sritejpalika}"
REMOTE_BASE="/home/${REMOTE_USER}"
REMOTE_APP="${REMOTE_BASE}/trading-app"

echo "🔧 Preparing ${INSTANCE} filesystem for scp (chown ${REMOTE_USER})..."
gcloud compute ssh "$INSTANCE" \
  --zone="$ZONE" --project="$PROJECT" --quiet \
  --command="sudo chown -R ${REMOTE_USER}:${REMOTE_USER} ${REMOTE_APP} ${REMOTE_BASE}/cpp_core ${REMOTE_BASE}/fyers-mcp-server 2>/dev/null || true; \
             sudo find ${REMOTE_APP} -type d -exec chmod u+rwx {} + 2>/dev/null || true; \
             sudo find ${REMOTE_APP} -type f -exec chmod u+rw {} + 2>/dev/null || true"
echo "✅ Remote prep complete"
