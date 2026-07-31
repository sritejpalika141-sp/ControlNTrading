#!/usr/bin/env python3
"""
ORB backtest using Fyers historical data (index + ATM option candles).

Requires authenticated Fyers session (FYERS_CLIENT_ID, access token in DB or env).
Without credentials, exits with instructions — use backtest_orb_premium.py for offline proxy.

Usage:
  cd trading-app && .venv/bin/python scripts/backtest_orb_fyers.py --days 30 --user-id 1
"""
from __future__ import annotations

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, APP_DIR)
sys.path.insert(0, SCRIPT_DIR)

IST_SYMBOL = "NSE:NIFTY50-INDEX"


def _fyers_ready(user_id: int) -> bool:
    """Lightweight auth probe — avoids full app bootstrap when creds are absent."""
    if os.environ.get("FYERS_CLIENT_ID") and os.environ.get("FYERS_ACCESS_TOKEN"):
        return True
    db_path = os.path.join(APP_DIR, "trading_app.db")
    if not os.path.isfile(db_path):
        return False
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT fyers_access_token FROM users WHERE id = ? LIMIT 1",
            (user_id,),
        ).fetchone()
        conn.close()
        return bool(row and row[0])
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="ORB backtest via Fyers historical API")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--output", default="reports/orb_fyers_backtest.json")
    args = parser.parse_args()

    if not _fyers_ready(args.user_id):
        print(
            "❌ Fyers not authenticated in this environment.\n"
            "   Set up FYERS credentials on the VM or local .env, then re-run.\n"
            "   Offline alternative:\n"
            "   .venv/bin/python scripts/backtest_orb_premium.py --days 59"
        )
        sys.exit(2)

    from backtest_orb import backtest_orb

    client = FyersClient(user_id=args.user_id)
    candles_5m = client.get_history_range(IST_SYMBOL, "5", days_back=args.days)
    candles_daily = client.get_history_range(IST_SYMBOL, "D", days_back=max(args.days, 90))
    if not candles_5m:
        print("❌ No Fyers 5m history returned")
        sys.exit(1)

    report = backtest_orb(candles_5m, candles_daily, vix_assumption=16.0)
    report["data_source"] = "fyers"
    report["symbol"] = IST_SYMBOL

    out = args.output if os.path.isabs(args.output) else os.path.join(APP_DIR, args.output)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(report, f, indent=2)

    print(json.dumps({k: v for k, v in report.items() if k != "trade_log"}, indent=2))
    print(f"💾 {out}")
    sys.exit(0 if report.get("pass_gate") else 1)


if __name__ == "__main__":
    main()
