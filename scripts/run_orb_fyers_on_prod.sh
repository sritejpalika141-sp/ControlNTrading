#!/usr/bin/env bash
# Run ORB Fyers backtest on the production VM (uses live .env + DB tokens).
# Requires: GCP_CREDENTIALS or gcloud auth (see scripts/gcloud_auth_from_env.sh).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=gcloud_auth_from_env.sh
source "$SCRIPT_DIR/gcloud_auth_from_env.sh"

PROJECT="${GCP_PROJECT:-sritej-trading-algo-2026}"
INSTANCE="${GCP_INSTANCE:-sritej-trading}"
ZONE="${GCP_ZONE:-asia-south1-c}"
REMOTE_USER="${GCP_REMOTE_USER:-sritejpalika}"
DAYS="${1:-30}"
USER_ID="${2:-1}"
LOCAL_REPORT="${3:-trading-app/reports/orb_fyers_backtest.json}"

echo "📊 Running backtest_orb_fyers.py on $INSTANCE (${DAYS}d, user $USER_ID)..."

# Ensure VM files are writable before any optional sync from CI
# shellcheck source=gcloud_remote_prep.sh
source "$SCRIPT_DIR/gcloud_remote_prep.sh"

gcloud compute ssh "$INSTANCE" \
  --zone="$ZONE" --project="$PROJECT" --quiet \
  --command="sudo -u $REMOTE_USER bash -lc 'cd /home/$REMOTE_USER/trading-app && .venv/bin/python scripts/backtest_orb_fyers.py --days $DAYS --user-id $USER_ID --output reports/orb_fyers_backtest.json'"

mkdir -p "$(dirname "$LOCAL_REPORT")"
gcloud compute scp \
  "$INSTANCE:/home/$REMOTE_USER/trading-app/reports/orb_fyers_backtest.json" \
  "$LOCAL_REPORT" \
  --zone="$ZONE" --project="$PROJECT" --quiet

echo "✅ Report copied to $LOCAL_REPORT"
