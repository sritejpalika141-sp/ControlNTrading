#!/usr/bin/env bash
# Enable ORB+S9 shadow (paper) week on production VM trading state.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=gcloud_auth_from_env.sh
source "$SCRIPT_DIR/gcloud_auth_from_env.sh"

PROJECT="${GCP_PROJECT:-sritej-trading-algo-2026}"
INSTANCE="${GCP_INSTANCE:-sritej-trading}"
ZONE="${GCP_ZONE:-asia-south1-c}"
REMOTE_USER="${GCP_REMOTE_USER:-sritejpalika}"
USER_ID="${1:-1}"
DAYS="${2:-7}"

echo "👻 Enabling ORB+S9 shadow week on $INSTANCE (user $USER_ID, ${DAYS}d)..."
gcloud compute ssh "$INSTANCE" \
  --zone="$ZONE" --project="$PROJECT" --quiet \
  --command="sudo -u $REMOTE_USER bash -lc 'cd /home/$REMOTE_USER/trading-app && .venv/bin/python scripts/enable_orb_s9_shadow_week.py --user-id $USER_ID --days $DAYS && .venv/bin/python scripts/enforce_backtest_shadow_gates.py --user-id $USER_ID --days 14 --app-dir . --state-dir logs'"
echo "✅ Shadow week + backtest gate enforcement applied on production"
