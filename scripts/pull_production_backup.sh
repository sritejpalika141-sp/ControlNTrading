#!/usr/bin/env bash
# Pull production trading-app artifacts from GCP VM to local backups/ for offline analysis.
# Requires: gcloud CLI authenticated (GCP_CREDENTIALS or gcloud auth login).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="$REPO_ROOT/backups/production/$(date +%Y%m%d_%H%M%S)"

PROJECT="${GCP_PROJECT:-sritej-trading-algo-2026}"
INSTANCE="${GCP_INSTANCE:-sritej-trading}"
ZONE="${GCP_ZONE:-asia-south1-c}"
REMOTE_USER="${GCP_REMOTE_USER:-sritejpalika}"
REMOTE_APP="/home/$REMOTE_USER/trading-app"

mkdir -p "$BACKUP_DIR"

# Authenticate gcloud (GCP_CREDENTIALS secret, GOOGLE_APPLICATION_CREDENTIALS, or existing login)
# shellcheck source=gcloud_auth_from_env.sh
source "$SCRIPT_DIR/gcloud_auth_from_env.sh"

if ! command -v gcloud >/dev/null 2>&1; then
  echo "❌ gcloud not found. Install: https://cloud.google.com/sdk/docs/install"
  exit 1
fi

echo "📥 Pulling from $INSTANCE ($ZONE) → $BACKUP_DIR"

gcloud compute scp --recurse \
  "$INSTANCE:$REMOTE_APP/app.py" \
  "$INSTANCE:$REMOTE_APP/models.py" \
  "$INSTANCE:$REMOTE_APP/state.py" \
  "$INSTANCE:$REMOTE_APP/fyers_client.py" \
  "$INSTANCE:$REMOTE_APP/git_info.txt" \
  "$BACKUP_DIR/" \
  --zone="$ZONE" --project="$PROJECT" --quiet

gcloud compute scp --recurse \
  "$INSTANCE:$REMOTE_APP/engine" \
  "$INSTANCE:$REMOTE_APP/workers" \
  "$INSTANCE:$REMOTE_APP/static" \
  "$BACKUP_DIR/" \
  --zone="$ZONE" --project="$PROJECT" --quiet

echo "📥 Pulling SQLite DB (SENSITIVE — live trading data)..."
gcloud compute scp \
  "$INSTANCE:$REMOTE_APP/trading_app.db" \
  "$BACKUP_DIR/trading_app.db" \
  --zone="$ZONE" --project="$PROJECT" --quiet || echo "⚠️  DB pull skipped (permissions or missing file)"

{
  echo "Pull Time: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  echo "Instance: $INSTANCE"
  echo "Zone: $ZONE"
  gcloud compute ssh "$INSTANCE" --zone="$ZONE" --project="$PROJECT" --quiet \
    --command="cd $REMOTE_APP && git rev-parse HEAD 2>/dev/null; head -8 git_info.txt 2>/dev/null" || true
} > "$BACKUP_DIR/production_manifest.txt"

echo "✅ Backup complete: $BACKUP_DIR"
echo "   Compare: diff -ru trading-app/ $BACKUP_DIR/ | head"
