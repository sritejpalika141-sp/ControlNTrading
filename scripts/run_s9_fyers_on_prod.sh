#!/usr/bin/env bash
# Run Strategy 9 Fyers backtest on the production VM.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=gcloud_auth_from_env.sh
source "$SCRIPT_DIR/gcloud_auth_from_env.sh"

PROJECT="${GCP_PROJECT:-sritej-trading-algo-2026}"
INSTANCE="${GCP_INSTANCE:-sritej-trading}"
ZONE="${GCP_ZONE:-asia-south1-c}"
REMOTE_USER="${GCP_REMOTE_USER:-sritejpalika}"
DAYS="${1:-59}"
USER_ID="${2:-1}"
LOCAL_REPORT="${3:-trading-app/reports/s9_fyers_backtest.json}"

echo "📊 Running backtest_s9_fyers.py on $INSTANCE (${DAYS}d, user $USER_ID)..."

# shellcheck source=gcloud_remote_prep.sh
source "$SCRIPT_DIR/gcloud_remote_prep.sh"

gcloud compute ssh "$INSTANCE" \
  --zone="$ZONE" --project="$PROJECT" --quiet \
  --command="sudo -u $REMOTE_USER bash -lc 'cd /home/$REMOTE_USER/trading-app && .venv/bin/python scripts/backtest_s9_fyers.py --days $DAYS --user-id $USER_ID --output reports/s9_fyers_backtest.json'" \
  || BACKTEST_EXIT=$?
BACKTEST_EXIT="${BACKTEST_EXIT:-0}"

mkdir -p "$(dirname "$LOCAL_REPORT")"
if gcloud compute scp \
  "$INSTANCE:/home/$REMOTE_USER/trading-app/reports/s9_fyers_backtest.json" \
  "$LOCAL_REPORT" \
  --zone="$ZONE" --project="$PROJECT" --quiet; then
  echo "✅ Report copied to $LOCAL_REPORT"
else
  echo "⚠️  Could not copy S9 report from VM"
  exit "${BACKTEST_EXIT:-1}"
fi
exit "$BACKTEST_EXIT"
