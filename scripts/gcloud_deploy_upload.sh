#!/usr/bin/env bash
# Upload trading-app (and optional cpp_core) to GCP VM via /tmp tarball + sudo rsync.
# Avoids scp "Permission denied" when CI SSH user != file owner on the VM.
# Usage (from repo root): source scripts/gcloud_deploy_upload.sh && upload_trading_app_bundle ...
set -euo pipefail

upload_trading_app_bundle() {
  local local_app="$1"
  local vm_orchestrator="$2"
  local instance="$3"
  local zone="$4"
  local project="$5"
  local remote_user="$6"
  local remote_app="/home/${remote_user}/trading-app"

  local tarball stage
  tarball="$(mktemp /tmp/sritej-app-XXXXXX.tar.gz)"
  stage="$(mktemp -d)"

  echo "  📦 Building trading-app bundle..."
  mkdir -p "${stage}/trading-app"
  rsync -a \
    --exclude 'trading_app.db' \
    --exclude '.env' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    "${local_app}/" "${stage}/trading-app/"
  cp "${vm_orchestrator}" "${stage}/trading-app/vm_orchestrator.py"
  tar -czf "${tarball}" -C "${stage}" trading-app
  rm -rf "${stage}"

  echo "  📤 Uploading bundle to /tmp (staging)..."
  gcloud compute scp "${tarball}" "${instance}:/tmp/sritej-deploy.tar.gz" \
    --zone="${zone}" --project="${project}" --quiet
  rm -f "${tarball}"

  echo "  📂 Installing bundle on VM (sudo rsync)..."
  gcloud compute ssh "${instance}" --zone="${zone}" --project="${project}" --quiet --command="
    set -e
    EXTRACT=/tmp/sritej-extract-\$\$
    mkdir -p \"\${EXTRACT}\"
    tar xzf /tmp/sritej-deploy.tar.gz -C \"\${EXTRACT}\"
    sudo rsync -a --exclude trading_app.db --exclude .env \"\${EXTRACT}/trading-app/\" \"${remote_app}/\"
    sudo chown -R ${remote_user}:${remote_user} \"${remote_app}\"
    rm -rf \"\${EXTRACT}\" /tmp/sritej-deploy.tar.gz
  "
  echo "  ✅ trading-app installed"
}

upload_cpp_core_bundle() {
  local cpp_dir="$1"
  local instance="$2"
  local zone="$3"
  local project="$4"
  local remote_user="$5"
  local remote_base="/home/${remote_user}"

  local tarball
  tarball="$(mktemp /tmp/sritej-cpp-XXXXXX.tar.gz)"
  tar -czf "${tarball}" -C "$(dirname "${cpp_dir}")" "$(basename "${cpp_dir}")"

  gcloud compute scp "${tarball}" "${instance}:/tmp/sritej-cpp.tar.gz" \
    --zone="${zone}" --project="${project}" --quiet
  rm -f "${tarball}"

  gcloud compute ssh "${instance}" --zone="${zone}" --project="${project}" --quiet --command="
    set -e
    EXTRACT=/tmp/sritej-cpp-extract-\$\$
    mkdir -p \"\${EXTRACT}\"
    tar xzf /tmp/sritej-cpp.tar.gz -C \"\${EXTRACT}\"
    sudo rsync -a \"\${EXTRACT}/cpp_core/\" \"${remote_base}/cpp_core/\"
    sudo chown -R ${remote_user}:${remote_user} \"${remote_base}/cpp_core\"
    rm -rf \"\${EXTRACT}\" /tmp/sritej-cpp.tar.gz
  "
  echo "  ✅ cpp_core installed"
}

upload_file_to_remote_path() {
  local local_file="$1"
  local instance="$2"
  local remote_dest="$3"
  local zone="$4"
  local project="$5"
  local remote_user="$6"
  local base
  base="$(basename "${local_file}")"

  gcloud compute scp "${local_file}" "${instance}:/tmp/${base}" \
    --zone="${zone}" --project="${project}" --quiet
  gcloud compute ssh "${instance}" --zone="${zone}" --project="${project}" --quiet --command="
    sudo mkdir -p \"$(dirname "${remote_dest}")\"
    sudo cp \"/tmp/${base}\" \"${remote_dest}\"
    sudo chown ${remote_user}:${remote_user} \"${remote_dest}\"
    rm -f \"/tmp/${base}\"
  "
}

upload_dir_to_remote_app_subpath() {
  local local_dir="$1"
  local instance="$2"
  local remote_subpath="$3"
  local zone="$4"
  local project="$5"
  local remote_user="$6"
  local remote_app="/home/${remote_user}/trading-app"
  local remote_dest="${remote_app}/${remote_subpath}"
  local tarball stage name
  name="$(basename "${local_dir}")"
  tarball="$(mktemp /tmp/sritej-dir-XXXXXX.tar.gz)"
  stage="$(mktemp -d)"
  cp -a "${local_dir}" "${stage}/${name}"
  tar -czf "${tarball}" -C "${stage}" "${name}"
  rm -rf "${stage}"

  gcloud compute scp "${tarball}" "${instance}:/tmp/sritej-dir.tar.gz" \
    --zone="${zone}" --project="${project}" --quiet
  rm -f "${tarball}"

  gcloud compute ssh "${instance}" --zone="${zone}" --project="${project}" --quiet --command="
    set -e
    EXTRACT=/tmp/sritej-dir-extract-\$\$
    mkdir -p \"\${EXTRACT}\"
    tar xzf /tmp/sritej-dir.tar.gz -C \"\${EXTRACT}\"
    sudo mkdir -p \"${remote_dest}\"
    sudo rsync -a \"\${EXTRACT}/${name}/\" \"${remote_dest}/\"
    sudo chown -R ${remote_user}:${remote_user} \"${remote_dest}\"
    rm -rf \"\${EXTRACT}\" /tmp/sritej-dir.tar.gz
  "
}
