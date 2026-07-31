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


def _has_stored_fyers_creds(user_id: int) -> bool:
    """True if DB has access or refresh token (OAuth may store refresh only)."""
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
    """Build FyersClient; refresh access token from refresh_token if needed."""
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
    parser = argparse.ArgumentParser(description="ORB backtest via Fyers historical API")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--output", default="reports/orb_fyers_backtest.json")
    args = parser.parse_args()

    if not _has_stored_fyers_creds(args.user_id):
        print(
            "❌ Fyers not authenticated in this environment.\n"
            "   Complete Fyers OAuth on prod (/login), then re-run.\n"
            "   Offline alternative:\n"
            "   .venv/bin/python scripts/backtest_orb_premium.py --days 59"
        )
        sys.exit(2)

    from backtest_orb import backtest_orb

    client = _ensure_fyers_client(args.user_id)
    if not client:
        print("❌ Could not initialize Fyers client (refresh token may need PIN/secret in DB).")
        sys.exit(2)
    candles_5m = client.get_history_range(IST_SYMBOL, "5", days_back=args.days)
    candles_daily = client.get_history_range(IST_SYMBOL, "D", days_back=max(args.days, 90))
    if not candles_5m:
        print("❌ No Fyers 5m history returned")
        sys.exit(1)

    report = backtest_orb(candles_5m, candles_daily, vix_assumption=16.0, symbol=IST_SYMBOL)
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
