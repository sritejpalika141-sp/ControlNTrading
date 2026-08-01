#!/bin/bash
# ============================================
# Sritej Trading v6.0.0 — One-Command Deploy
# ============================================
# Usage: bash deploy.sh
# ============================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCAL_APP="$SCRIPT_DIR/trading-app"
LOCAL_FYERS="$SCRIPT_DIR/fyers-mcp-server"

# GCP VM Details
PROJECT="sritej-trading-algo-2026"
INSTANCE="sritej-trading"
ZONE="asia-south1-c"
REMOTE_USER="sritejpalika"
REMOTE_BASE="/home/$REMOTE_USER"
REMOTE_APP="$REMOTE_BASE/trading-app"
REMOTE_FYERS="$REMOTE_BASE/fyers-mcp-server"
PORT="8000"

echo ""
echo "🚀 Sritej Trading v6.0.0 — One-Command Deploy"
echo "============================================"
echo ""

# ─── Step 1: Verify VM is running ───
echo "🔍 Step 1: Checking VM status..."
VM_STATUS=$(gcloud compute instances describe "$INSTANCE" --zone="$ZONE" --project="$PROJECT" --format="value(status)" 2>/dev/null)
if [ "$VM_STATUS" != "RUNNING" ]; then
    echo "⚠️  VM is $VM_STATUS. Starting it..."
    gcloud compute instances start "$INSTANCE" --zone="$ZONE" --project="$PROJECT"
    echo "⏳ Waiting 30s for VM to boot..."
    sleep 30
fi
echo "✅ VM is running."

# ─── Step 2: Pre-deploy syntax validation ───
echo ""
echo "🧪 Step 2: Validating Python syntax..."
VALIDATION_FAILED=0
for pyfile in "$LOCAL_APP/app.py" "$LOCAL_APP/fyers_client.py" "$LOCAL_APP/models.py" "$LOCAL_APP/state.py"; do
    if [ -f "$pyfile" ]; then
        python3 -c "import py_compile; py_compile.compile('$pyfile', doraise=True)" 2>&1
        if [ $? -ne 0 ]; then
            echo "❌ SYNTAX ERROR in $(basename $pyfile)! Aborting deploy."
            VALIDATION_FAILED=1
        fi
    fi
done
for pyfile in "$LOCAL_APP"/engine/*.py "$LOCAL_APP"/workers/*.py; do
    if [ -f "$pyfile" ]; then
        python3 -c "import py_compile; py_compile.compile('$pyfile', doraise=True)" 2>&1
        if [ $? -ne 0 ]; then
            echo "❌ SYNTAX ERROR in $(basename $pyfile)! Aborting deploy."
            VALIDATION_FAILED=1
        fi
    fi
done
if [ $VALIDATION_FAILED -ne 0 ]; then
    echo ""
    echo "🛑 Deploy ABORTED due to syntax errors. Fix them first."
    exit 1
fi
echo "✅ All Python files validated."

# ─── Step 3: Upload files (via /tmp staging — CI SSH user cannot overwrite app dir directly) ───
echo ""
echo "📤 Step 3: Uploading files to cloud..."

# shellcheck source=scripts/gcloud_deploy_upload.sh
source "$SCRIPT_DIR/scripts/gcloud_deploy_upload.sh"

# Generate git info file from local repo
echo "  📝 Generating git info..."
GIT_INFO_FILE="$LOCAL_APP/git_info.txt"
{
    echo "Deploy Time: $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "Branch: $(git -C "$SCRIPT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')"
    echo "---"
    git -C "$SCRIPT_DIR" log -n 10 --format="%h %s (%cr)" 2>/dev/null || echo "No git history available"
} > "$GIT_INFO_FILE"

upload_trading_app_bundle "$LOCAL_APP" "$SCRIPT_DIR/vm_orchestrator.py" \
  "$INSTANCE" "$ZONE" "$PROJECT" "$REMOTE_USER"

echo "  ⚡ C++ HFT Core files..."
if [ -d "$SCRIPT_DIR/cpp_core" ]; then
    upload_cpp_core_bundle "$SCRIPT_DIR/cpp_core" "$INSTANCE" "$ZONE" "$PROJECT" "$REMOTE_USER"
else
    echo "  ⚠️  Skipping cpp_core (not in repository)"
fi

echo "  📂 Fyers credentials..."
if [ -f "$LOCAL_FYERS/.env" ]; then
    upload_file_to_remote_path "$LOCAL_FYERS/.env" "$INSTANCE" "$REMOTE_FYERS/.env" \
      "$ZONE" "$PROJECT" "$REMOTE_USER"
else
    echo "  ⚠️  Skipping fyers-mcp-server/.env (not present locally)"
fi

if [ -f "$LOCAL_APP/.env" ]; then
    upload_file_to_remote_path "$LOCAL_APP/.env" "$INSTANCE" "$REMOTE_APP/.env" \
      "$ZONE" "$PROJECT" "$REMOTE_USER"
fi

# ─── Step 3.5: Create & upload a remote restart script ───
RESTART_SCRIPT=$(mktemp "$SCRIPT_DIR/restart_remote_XXXX.sh")
cat > "$RESTART_SCRIPT" << 'REMOTE_EOF'
#!/bin/bash
APP_DIR="/home/sritejpalika/trading-app"
CPP_DIR="/home/sritejpalika/cpp_core"
PORT=8000

echo "⚡ Compiling Native C++ HFT Core on VM..."
if ! command -v cmake &> /dev/null || ! command -v g++ &> /dev/null; then
    echo "📦 Installing build-essential & cmake on VM..."
    sudo apt-get update -qq && sudo apt-get install -y cmake build-essential g++ >/dev/null 2>&1
fi

if [ -d "$CPP_DIR" ]; then
    # CI SSH user may not own build artifacts — always use sudo for clean/rebuild.
    sudo rm -rf "$CPP_DIR/build" || true
    sudo mkdir -p "$CPP_DIR/build"
    sudo chown -R sritejpalika:sritejpalika "$CPP_DIR" || true
    if (cd "$CPP_DIR/build" && cmake .. && make -j4); then
        mkdir -p "$APP_DIR/cpp_core/build"
        cp -f "$CPP_DIR/build/libcpp_core.so" "$APP_DIR/cpp_core/build/" 2>/dev/null || true
        echo "✅ C++ HFT Core compiled successfully!"
    else
        echo "⚠️  C++ HFT Core build skipped/failed — Python fallback remains active"
    fi
else
    echo "⚠️  cpp_core directory missing on VM — skipping native build"
fi

echo "📦 Ensuring healthy .venv + dependencies..."
# Recreate venv if missing or broken (e.g. pip shebang points at a Mac laptop path).
NEED_VENV=0
if [ ! -x "$APP_DIR/.venv/bin/python" ] && [ ! -x "$APP_DIR/.venv/bin/python3" ]; then
    NEED_VENV=1
elif ! sudo -u sritejpalika "$APP_DIR/.venv/bin/python" -c "import sys; print(sys.version)" >/dev/null 2>&1 \
   && ! sudo -u sritejpalika "$APP_DIR/.venv/bin/python3" -c "import sys; print(sys.version)" >/dev/null 2>&1; then
    NEED_VENV=1
fi
if [ "$NEED_VENV" = "1" ]; then
    echo "♻️  Recreating .venv with system python3 (as sritejpalika)..."
    sudo rm -rf "$APP_DIR/.venv"
    sudo -u sritejpalika python3 -m venv "$APP_DIR/.venv"
fi
PY="$APP_DIR/.venv/bin/python3"
[ -x "$PY" ] || PY="$APP_DIR/.venv/bin/python"
# Always install as the app owner — CI SSH user cannot write into .venv owned by sritejpalika.
sudo -u sritejpalika "$PY" -m pip install --upgrade pip setuptools wheel --quiet 2>/dev/null || true
sudo -u sritejpalika "$PY" -m pip install -r "$APP_DIR/requirements.txt" --quiet 2>&1 | tail -8
# Ensure uvicorn entrypoint exists for systemd ExecStart
if [ ! -x "$APP_DIR/.venv/bin/python" ] && [ -x "$APP_DIR/.venv/bin/python3" ]; then
    sudo -u sritejpalika ln -sfn python3 "$APP_DIR/.venv/bin/python"
fi
# Verify critical import before restart
if ! sudo -u sritejpalika "$PY" -c "import uvicorn, fastapi" >/dev/null 2>&1; then
    echo "❌ venv still missing uvicorn/fastapi after pip install"
    sudo -u sritejpalika "$PY" -m pip install 'uvicorn[standard]' fastapi --quiet 2>&1 | tail -5
fi

echo "🔒 Refreshing OS security packages (openssl, ca-certificates, curl)..."
sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq 2>/dev/null || true
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --only-upgrade openssl ca-certificates curl 2>/dev/null | tail -5 || true

# Set permissions
sudo chown -R sritejpalika:sritejpalika $APP_DIR/ 2>/dev/null || true
sudo chmod -R 755 $APP_DIR/static 2>/dev/null || true

if systemctl is-enabled sritej-trading >/dev/null 2>&1; then
    echo "⚙️ Systemd service detected. Restarting via systemctl..."
    # Ensure any manual uvicorn on the port is killed first to avoid conflicts
    sudo fuser -k $PORT/tcp 2>/dev/null || true
    pkill -9 -f 'uvicorn app:app' 2>/dev/null || true
    sleep 1
    
    sudo systemctl restart sritej-trading
    sleep 6
    if sudo systemctl is-active sritej-trading >/dev/null 2>&1; then
        echo "✅ App is RUNNING under systemd"
    else
        echo "❌ App systemd service is NOT active. Status:"
        sudo systemctl status sritej-trading --no-pager
    fi
    
    # --- Setup VM Orchestrator Service ---
    echo "⚙️ Setting up Cloud VM Orchestrator (sritej-orchestrator)..."
    cat << 'SVC_EOF' | sudo tee /etc/systemd/system/sritej-orchestrator.service >/dev/null
[Unit]
Description=Sritej Trading VM Orchestrator
After=network.target sritej-trading.service

[Service]
User=sritejpalika
WorkingDirectory=/home/sritejpalika/trading-app
ExecStart=/home/sritejpalika/trading-app/.venv/bin/python3 /home/sritejpalika/trading-app/vm_orchestrator.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVC_EOF
    sudo systemctl daemon-reload
    sudo systemctl enable sritej-orchestrator
    sudo systemctl restart sritej-orchestrator
    echo "✅ VM Orchestrator is RUNNING!"
    # ------------------------------------

    # --- Setup Strategy Researcher Service ---
    echo "⚙️ Setting up Strategy Researcher (sritej-researcher)..."
    cat << 'SVC_EOF' | sudo tee /etc/systemd/system/sritej-researcher.service >/dev/null
[Unit]
Description=Sritej Trading Strategy Researcher (GitHub Learner)
After=network.target

[Service]
User=sritejpalika
WorkingDirectory=/home/sritejpalika/trading-app
ExecStart=/home/sritejpalika/trading-app/.venv/bin/python3 /home/sritejpalika/trading-app/strategy_researcher.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVC_EOF
    sudo systemctl daemon-reload
    sudo systemctl enable sritej-researcher
    sudo systemctl restart sritej-researcher
    echo "✅ Strategy Researcher is RUNNING!"
    # ------------------------------------
else
    echo "🔄 Stopping old manual processes..."
    sudo fuser -k $PORT/tcp 2>/dev/null || true
    pkill -9 -f 'uvicorn app:app' 2>/dev/null || true
    sleep 2

    echo "🚀 Starting app manually..."
    cd $APP_DIR && nohup python3 -m uvicorn app:app --host 0.0.0.0 --port $PORT --loop uvloop > app.log 2>&1 &
    sleep 8

    if pgrep -f 'uvicorn app:app' > /dev/null; then
        echo "✅ App is RUNNING (PID: $(pgrep -f 'uvicorn app:app'))"
    else
        echo "❌ App FAILED. Last 30 lines:"
        tail -30 $APP_DIR/app.log
    fi
fi
echo ""
tail -10 $APP_DIR/app.log 2>/dev/null
REMOTE_EOF
chmod +x "$RESTART_SCRIPT"

echo "  📂 Restart script..."
REMOTE_RESTART="/tmp/sritej-restart-$(date +%s).sh"
gcloud compute scp "$RESTART_SCRIPT" "$INSTANCE:$REMOTE_RESTART" --zone="$ZONE" --project="$PROJECT" --quiet
rm -f "$RESTART_SCRIPT"

echo "✅ All files uploaded."

# ─── Step 4: Run restart script on server ───
echo ""
echo "🔄 Step 4: Installing deps & restarting on VM..."
gcloud compute ssh "$INSTANCE" --zone="$ZONE" --project="$PROJECT" --quiet --command="bash $REMOTE_RESTART && rm -f $REMOTE_RESTART"
SSH_EXIT=$?

if [ $SSH_EXIT -ne 0 ]; then
    echo ""
    echo "⚠️  SSH failed (exit $SSH_EXIT). Files uploaded OK."
    echo "   SSH into server manually and run:"
    echo "   bash /tmp/restart_app.sh"
    echo ""
fi

# ─── Step 5: Health check ───
echo ""
echo "🏥 Step 5: Health check..."
EXTERNAL_IP=$(gcloud compute instances describe "$INSTANCE" --zone="$ZONE" --project="$PROJECT" --format="value(networkInterfaces[0].accessConfigs[0].natIP)")

for i in 1 2 3 4 5; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 10 "http://$EXTERNAL_IP:$PORT/" 2>/dev/null)
    if [ "$CODE" = "200" ]; then
        echo "✅ Health check PASSED! Dashboard is live (HTTP 200 OK)."
        break
    fi
    if [ $i -lt 5 ]; then
        echo "  ⏳ Attempt $i failed (HTTP $CODE), retrying in 5s..."
        sleep 5
    else
        echo "⚠️  Health check failed. Manual fix:"
        echo "  1. gcloud compute ssh $INSTANCE --zone=$ZONE --project=$PROJECT"
        echo "  2. bash /tmp/restart_app.sh"
    fi
done

# ─── Done ───
echo ""
echo "============================================"
echo "✅ DEPLOY COMPLETE!"
echo "🌐 Dashboard: http://$EXTERNAL_IP:$PORT"
echo "============================================"
echo ""
