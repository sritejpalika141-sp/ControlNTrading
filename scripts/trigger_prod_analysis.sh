#!/usr/bin/env bash
# Trigger GitHub Actions prod-analysis workflow (uses repo GCP_CREDENTIALS — no Cursor secret).
set -euo pipefail

DAYS="${1:-30}"
USER_ID="${2:-1}"
REPO="${GITHUB_REPOSITORY:-sritejpalika141-sp/ControlNTrading}"

echo "🚀 Triggering Production Analysis workflow (days=$DAYS user=$USER_ID)..."
gh workflow run prod-analysis.yml \
  -R "$REPO" \
  -f "backtest_days=$DAYS" \
  -f "user_id=$USER_ID"

echo "⏳ Waiting for workflow run to appear..."
sleep 8
RUN_ID="$(gh run list -R "$REPO" --workflow=prod-analysis.yml --limit 1 --json databaseId -q '.[0].databaseId')"
echo "Run ID: $RUN_ID"
echo "URL: https://github.com/$REPO/actions/runs/$RUN_ID"

echo "⏳ Waiting for completion (up to 15 min)..."
gh run watch "$RUN_ID" -R "$REPO" --interval 15 --exit-status

OUT_DIR="${3:-backups/ci-download}"
mkdir -p "$OUT_DIR"
gh run download "$RUN_ID" -R "$REPO" -n prod-analysis -D "$OUT_DIR"
echo "✅ Artifacts saved under $OUT_DIR"
