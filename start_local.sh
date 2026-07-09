#!/bin/bash
# ============================================
# Sritej Trading v5.0.0 — Local Development
# Start the trading dashboard locally
# ============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/trading-app"
VENV_DIR="$APP_DIR/.venv"
PORT="${PORT:-8000}"

echo "🚀 Sritej Trading — Local Start"
echo "================================"

# Check if venv exists
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "📦 Installing dependencies..."
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
    echo "✅ Environment ready!"
fi

# Activate and run
cd "$APP_DIR"
echo "🌐 Starting on http://localhost:$PORT"
"$VENV_DIR/bin/python" -m uvicorn app:app --host 0.0.0.0 --port "$PORT" --reload
