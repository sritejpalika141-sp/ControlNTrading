"""
run_backtests.py — CLI entry point for engine/backtest_runner.py (04-08-26).

Fetches real historical underlying data (read-only, same class of call as any diagnostic
historical pull — no orders placed, no broker state touched) and backtests all 13 strategies
(11 equity/index + 2 crude), then saves results to the backtest_results table.

Usage:
    .venv/bin/python3 run_backtests.py [--days N] [--no-save]

See engine/backtest_engine.py's module docstring for what this backtest does and does not model
(synthetic Black-Scholes premiums, uniform SL/target rule) before trusting these numbers.
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime

import pytz

IST = pytz.timezone("Asia/Kolkata")


async def main():
    parser = argparse.ArgumentParser(description="Backtest all strategies against real historical data.")
    parser.add_argument("--days", type=int, default=60, help="Historical window in days (default 60).")
    parser.add_argument("--no-save", action="store_true", help="Print results only, don't write to backtest_results.")
    parser.add_argument("--user-id", type=int, default=1, help="Which user's Fyers credentials to use for the historical fetch.")
    args = parser.parse_args()

    for line in open(".env"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)
    sys.path.insert(0, ".")

    from fyers_client import FyersClient
    from engine.backtest_runner import run_all_backtests

    client = FyersClient(user_id=args.user_id)
    if not client.is_authenticated():
        print("❌ Fyers client is not authenticated — cannot fetch historical data. Log in first.")
        sys.exit(1)

    print(f"🔎 Running backtests ({args.days}-day window) for all 13 strategies — this makes real "
          f"historical data calls, no orders, no live state changes...")
    results = await run_all_backtests(client, days_back=args.days)

    run_date = datetime.now(IST).strftime("%Y-%m-%d")
    print("\n" + "=" * 100)
    print(f"{'STRATEGY':<42} {'SYMBOL':<24} {'TRADES':>7} {'WINS':>5} {'LOSS':>5} {'WIN%':>7} {'PnL(pts)':>10}")
    print("=" * 100)
    for r in results:
        note = r.get("error", "")
        print(f"{r['strategy']:<42} {r.get('symbol',''):<24} {r['trades']:>7} {r['wins']:>5} "
              f"{r['losses']:>5} {r['win_rate']:>6.1f}% {r['total_pnl']:>10.2f}" + (f"  ⚠️ {note}" if note else ""))
    print("=" * 100)

    if args.no_save:
        print("(--no-save: results NOT written to backtest_results)")
        return

    from models import Database
    saved = 0
    for r in results:
        ok = await Database.save_backtest_result(
            strategy_name=r["strategy"], symbol=r.get("symbol", ""), run_date=run_date,
            window_days=args.days, trades=r["trades"], wins=r["wins"], losses=r["losses"],
            win_rate=r["win_rate"], total_pnl=r["total_pnl"], avg_pnl=r["avg_pnl"],
            note=r.get("error", ""),
        )
        saved += int(ok)
    print(f"💾 Saved {saved}/{len(results)} results to backtest_results (run_date={run_date}).")


if __name__ == "__main__":
    asyncio.run(main())
