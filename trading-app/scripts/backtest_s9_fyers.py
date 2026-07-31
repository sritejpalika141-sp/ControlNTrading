#!/usr/bin/env python3
"""
Strategy 9 rules backtest using Fyers NIFTY 5m history (no yfinance).

Usage:
  cd trading-app && .venv/bin/python scripts/backtest_s9_fyers.py --days 59 --user-id 1
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


def _has_stored_fyers_creds(user_id: int) -> bool:
    if os.environ.get("FYERS_CLIENT_ID") and os.environ.get("FYERS_ACCESS_TOKEN"):
        return True
    db_path = os.path.join(APP_DIR, "trading_app.db")
    if not os.path.isfile(db_path):
        return False
    try:
        import sqlite3

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT fyers_access_token, fyers_refresh_token FROM users WHERE id = ? LIMIT 1",
            (user_id,),
        ).fetchone()
        conn.close()
        if not row:
            return False
        access, refresh = row[0], row[1]
        return bool((access and str(access).strip()) or (refresh and str(refresh).strip()))
    except Exception:
        return False


def _ensure_fyers_client(user_id: int):
    from fyers_client import FyersClient

    client = FyersClient(user_id=user_id)
    if client._get_active_client():
        return client
    if client.refresh_via_refresh_token():
        client.reinit_with_fresh_token()
    if client._get_active_client():
        return client
    return None


def main():
    parser = argparse.ArgumentParser(description="Strategy 9 rules backtest via Fyers")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--days", type=int, default=59)
    parser.add_argument("--output", default="reports/s9_fyers_backtest.json")
    args = parser.parse_args()

    if not _has_stored_fyers_creds(args.user_id):
        print(
            "❌ Fyers not authenticated.\n"
            "   Complete OAuth on prod, then re-run.\n"
            "   Offline: .venv/bin/python scripts/backtest_strategy9_rules.py --days 59"
        )
        sys.exit(2)

    from backtest_strategy9_rules import run_backtest

    client = _ensure_fyers_client(args.user_id)
    if not client:
        print("❌ Could not initialize Fyers client.")
        sys.exit(2)

    candles_5m = client.get_history_range(IST_SYMBOL, "5", days_back=args.days)
    if not candles_5m:
        print("❌ No Fyers 5m history returned")
        sys.exit(1)

    report = run_backtest(candles_5m)
    report["data_source"] = "fyers"
    report["symbol"] = IST_SYMBOL
    from datetime import datetime

    import pytz

    ist = pytz.timezone("Asia/Kolkata")
    report["sessions"] = len(
        {datetime.fromtimestamp(c["timestamp"], ist).strftime("%Y-%m-%d") for c in candles_5m}
    )

    out = args.output if os.path.isabs(args.output) else os.path.join(APP_DIR, args.output)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(report, f, indent=2)

    print(json.dumps({k: v for k, v in report.items() if k != "sample_trades"}, indent=2))
    print(f"💾 {out}")
    sys.exit(0 if report.get("pass_gate") else 1)


if __name__ == "__main__":
    main()
