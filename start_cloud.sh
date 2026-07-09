#!/bin/bash
# ============================================
# Sritej Trading v5.0.0 — Cloud Startup
# Runs on the GCP VM after deployment
# ============================================

set -e

APP_DIR="/home/sritejpalika/trading-app"
VENV_DIR="$APP_DIR/.venv"
PORT="${PORT:-8000}"
LOG_FILE="$APP_DIR/app.log"

echo "🚀 Sritej Trading — Cloud Start"
echo "================================"

# Kill any existing instance
echo "🔄 Stopping existing instance..."
pkill -f "uvicorn app:app" 2>/dev/null || true
sleep 2

# Check if venv exists
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "📦 Installing dependencies..."
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
    echo "✅ Environment ready!"
fi

# Start the app
cd "$APP_DIR"
echo "🌐 Starting on port $PORT..."
nohup "$VENV_DIR/bin/python" -m uvicorn app:app --host 0.0.0.0 --port "$PORT" > "$LOG_FILE" 2>&1 &

# Wait and verify
sleep 3
if pgrep -f "uvicorn app:app" > /dev/null; then
    echo "✅ Trading Dashboard running on port $PORT"
    echo "📋 Logs: tail -f $LOG_FILE"

    # Add cron job for daily restart at 6 AM IST if not present
    echo "⏰ Checking scheduled restart..."
    TZ_NAME=$(date +%Z)
    if [ "$TZ_NAME" = "UTC" ]; then
        # 6 AM IST = 00:30 UTC
        CRON_SCHEDULE="30 0 * * *"
    else
        # Default to 6 AM local time (assuming IST or handled by user)
        CRON_SCHEDULE="0 6 * * *"
    fi

    CRON_JOB="$CRON_SCHEDULE /bin/bash /home/sritejpalika/start_cloud.sh"
    crontab -l 2>/dev/null | grep -F "start_cloud.sh" > /dev/null
    if [ $? -ne 0 ]; then
        echo "📝 Adding daily restart to crontab ($CRON_SCHEDULE)..."
        (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
        echo "✅ Daily restart scheduled!"
    else
        echo "ℹ️ Daily restart already scheduled."
    fi
else
    echo "❌ Failed to start. Check logs:"
    tail -20 "$LOG_FILE"
    exit 1
fi
