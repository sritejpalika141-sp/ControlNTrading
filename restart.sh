#!/bin/bash
# Sritej Trading — Restart Script
echo "🔄 Stopping old server..."
pkill -f "uvicorn app:app" 2>/dev/null
sleep 2

echo "🚀 Starting trading app..."
cd "/Users/sritejpalika/Downloads/Sritej Trading/v5/trading-app"
.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8000
