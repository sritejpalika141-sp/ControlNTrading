#!/usr/bin/env bash
# Authenticate gcloud from GCP_CREDENTIALS (Cursor/GitHub secret) or existing login.
# Usage: source scripts/gcloud_auth_from_env.sh   OR   bash scripts/gcloud_auth_from_env.sh
set -euo pipefail

PROJECT="${GCP_PROJECT:-sritej-trading-algo-2026}"
ZONE="${GCP_ZONE:-asia-south1-c}"
INSTANCE="${GCP_INSTANCE:-sritej-trading}"

if ! command -v gcloud >/dev/null 2>&1; then
  echo "❌ gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
  return 1 2>/dev/null || exit 1
fi

_activate_from_file() {
  local key_file="$1"
  gcloud auth activate-service-account --key-file="$key_file" --quiet
  export GOOGLE_APPLICATION_CREDENTIALS="$key_file"
  echo "✅ gcloud authenticated via service account key ($key_file)"
}

if [[ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" && -f "${GOOGLE_APPLICATION_CREDENTIALS}" ]]; then
  echo "✅ Using GOOGLE_APPLICATION_CREDENTIALS=${GOOGLE_APPLICATION_CREDENTIALS}"
elif [[ -n "${GCP_CREDENTIALS:-}" ]]; then
  KEY_FILE="${GCP_KEY_FILE:-/tmp/gcp-sa-key.json}"
  printf '%s' "$GCP_CREDENTIALS" > "$KEY_FILE"
  chmod 600 "$KEY_FILE"
  _activate_from_file "$KEY_FILE"
elif [[ -n "${GCP_CREDENTIALS_FILE:-}" && -f "${GCP_CREDENTIALS_FILE}" ]]; then
  _activate_from_file "$GCP_CREDENTIALS_FILE"
else
  ACTIVE="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1 || true)"
  if [[ -z "$ACTIVE" ]]; then
    echo "❌ No GCP credentials available."
    echo "   Add Cursor secret GCP_CREDENTIALS (full service-account JSON), or run: gcloud auth login"
    return 1 2>/dev/null || exit 1
  fi
  echo "✅ Using existing gcloud account: $ACTIVE"
fi

gcloud config set project "$PROJECT" --quiet
gcloud compute config-ssh --quiet --project="$PROJECT" 2>/dev/null || true
echo "✅ gcloud project=$PROJECT instance=$INSTANCE zone=$ZONE"
