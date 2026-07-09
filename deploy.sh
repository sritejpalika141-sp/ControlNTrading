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

# ─── Step 3: Upload files ───
echo ""
echo "📤 Step 3: Uploading files to cloud..."

# Generate git info file from local repo
echo "  📝 Generating git info..."
GIT_INFO_FILE="$LOCAL_APP/git_info.txt"
{
    echo "Deploy Time: $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "Branch: $(git -C "$SCRIPT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')"
    echo "---"
    git -C "$SCRIPT_DIR" log -n 10 --format="%h %s (%cr)" 2>/dev/null || echo "No git history available"
} > "$GIT_INFO_FILE"

echo "  📂 Core files..."
gcloud compute scp \
    "$LOCAL_APP/app.py" \
    "$LOCAL_APP/auth_utils.py" \
    "$LOCAL_APP/fyers_client.py" \
    "$LOCAL_APP/models.py" \
    "$LOCAL_APP/state.py" \
    "$LOCAL_APP/requirements.txt" \
    "$LOCAL_APP/dailyupdates.md" \
    "$LOCAL_APP/git_info.txt" \
    "$SCRIPT_DIR/vm_orchestrator.py" \
    "$LOCAL_APP/strategy_researcher.py" \
    "$INSTANCE:$REMOTE_APP/" --zone="$ZONE" --project="$PROJECT" --quiet

echo "  📂 Engine modules..."
gcloud compute scp --recurse "$LOCAL_APP/engine" "$INSTANCE:$REMOTE_APP/" --zone="$ZONE" --project="$PROJECT" --quiet

echo "  📂 Worker modules..."
gcloud compute scp --recurse "$LOCAL_APP/workers" "$INSTANCE:$REMOTE_APP/" --zone="$ZONE" --project="$PROJECT" --quiet

echo "  📂 Data files..."
gcloud compute scp --recurse "$LOCAL_APP/data" "$INSTANCE:$REMOTE_APP/" --zone="$ZONE" --project="$PROJECT" --quiet

echo "  📂 Static assets..."
gcloud compute scp --recurse "$LOCAL_APP/static" "$INSTANCE:$REMOTE_APP/" --zone="$ZONE" --project="$PROJECT" --quiet

echo "  📂 Scripts (migrations)..."
gcloud compute scp --recurse "$LOCAL_APP/scripts" "$INSTANCE:$REMOTE_APP/" --zone="$ZONE" --project="$PROJECT" --quiet

echo "  📂 Fyers credentials..."
gcloud compute scp "$LOCAL_FYERS/.env" "$INSTANCE:$REMOTE_FYERS/.env" --zone="$ZONE" --project="$PROJECT" --quiet

if [ -f "$LOCAL_APP/.env" ]; then
    gcloud compute scp "$LOCAL_APP/.env" "$INSTANCE:$REMOTE_APP/.env" --zone="$ZONE" --project="$PROJECT" --quiet
fi

# ─── Step 3.5: Create & upload a remote restart script ───
RESTART_SCRIPT=$(mktemp "$SCRIPT_DIR/restart_remote_XXXX.sh")
cat > "$RESTART_SCRIPT" << 'REMOTE_EOF'
#!/bin/bash
APP_DIR="/home/sritejpalika/trading-app"
PORT=8000

echo "📦 Installing dependencies into .venv..."
$APP_DIR/.venv/bin/pip install -r $APP_DIR/requirements.txt --quiet 2>&1 | tail -3

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
gcloud compute scp "$RESTART_SCRIPT" "$INSTANCE:/tmp/restart_app.sh" --zone="$ZONE" --project="$PROJECT" --quiet
rm -f "$RESTART_SCRIPT"

echo "✅ All files uploaded."

# ─── Step 4: Run restart script on server ───
echo ""
echo "🔄 Step 4: Installing deps & restarting on VM..."
gcloud compute ssh "$INSTANCE" --zone="$ZONE" --project="$PROJECT" --quiet --command="bash /tmp/restart_app.sh"
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

for i in 1 2 3; do
    HEALTH=$(curl -s --connect-timeout 10 "http://$EXTERNAL_IP:$PORT/api/health" 2>/dev/null)
    if echo "$HEALTH" | grep -q '"status":"healthy"'; then
        echo "✅ Health check PASSED!"
        echo "   $HEALTH" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    print(f\"   Version: {d.get('version','?')} | Uptime: {d.get('uptime','?')} | Memory: {d.get('memory_mb','?')}MB | Users: {d.get('active_users',0)}\")
except: pass
" 2>/dev/null
        break
    fi
    if [ $i -lt 3 ]; then
        echo "  ⏳ Attempt $i failed, retrying in 8s..."
        sleep 8
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
