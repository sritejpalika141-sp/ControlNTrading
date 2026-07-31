#!/usr/bin/env python3
"""
ORB backtest with option-premium proxy PnL (delta model).

Uses the same entry filters as live ORB (orb_filters.py) but converts underlying
ORB range to option points via ORB_DELTA (default 0.55), matching strategy_orb.py.

When FYERS credentials are available, use scripts/backtest_orb_fyers.py for
historical ATM option candles instead.

Usage:
  cd trading-app && .venv/bin/python scripts/backtest_orb_premium.py --days 59
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

from backtest_orb import backtest_orb, fetch_candles  # noqa: E402

ORB_DELTA = 0.55
MAX_OPTION_SL_PTS = 50.0


def premium_pnl_from_spot_report(spot_report: dict, delta: float = ORB_DELTA) -> dict:
    """Re-score trades using per-trade ORB range → option SL/TP (1R / 2R)."""
    trades = []
    for t in spot_report.get("trade_log", []):
        orb_pct = t.get("orb_range_pct", 0.2)
        entry = t["entry"]
        orb_pts = entry * orb_pct / 100.0
        sl_pts = min(orb_pts * delta, MAX_OPTION_SL_PTS)
        tp_pts = sl_pts * 2.0
        pnl_spot = t["pnl_pts"]
        if pnl_spot >= tp_pts * (1 / delta):  # rough spot win at 2R
            pnl_opt = tp_pts
            outcome = "WIN"
        elif pnl_spot <= -sl_pts * (1 / delta):
            pnl_opt = -sl_pts
            outcome = "LOSS"
        else:
            # Scale spot move to option via delta
            pnl_opt = round(pnl_spot * delta, 2)
            outcome = "WIN" if pnl_opt > 0 else "LOSS"
        trades.append({**t, "outcome": outcome, "pnl_opt_pts": pnl_opt, "sl_opt_pts": round(sl_pts, 2)})

    wins = sum(1 for t in trades if t["outcome"] == "WIN")
    gross_win = sum(t["pnl_opt_pts"] for t in trades if t["pnl_opt_pts"] > 0)
    gross_loss = abs(sum(t["pnl_opt_pts"] for t in trades if t["pnl_opt_pts"] < 0))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
    total = sum(t["pnl_opt_pts"] for t in trades)

    return {
        "strategy": "Strategy 3 ORB (option premium proxy)",
        "delta_assumption": delta,
        "sessions": spot_report.get("sessions"),
        "trades": len(trades),
        "wins": wins,
        "losses": len(trades) - wins,
        "win_rate_pct": round((wins / len(trades) * 100) if trades else 0, 1),
        "profit_factor": round(pf, 2),
        "total_pnl_opt_pts": round(total, 1),
        "pass_gate": (wins / len(trades) >= 0.45 and pf >= 1.3) if trades else False,
        "skips": spot_report.get("skips"),
        "trade_log": trades,
    }


def main():
    parser = argparse.ArgumentParser(description="ORB backtest with option premium proxy")
    parser.add_argument("--symbol", default="^NSEI")
    parser.add_argument("--days", type=int, default=59)
    parser.add_argument("--vix", type=float, default=16.0)
    parser.add_argument("--delta", type=float, default=ORB_DELTA)
    parser.add_argument("--output", default="reports/orb_premium_backtest.json")
    args = parser.parse_args()

    print(f"📊 Fetching {args.days}d for {args.symbol}...")
    c5, cd = fetch_candles(args.symbol, args.days)
    if not c5:
        sys.exit(1)

    spot_report = backtest_orb(c5, cd, vix_assumption=args.vix)
    report = premium_pnl_from_spot_report(spot_report, delta=args.delta)
    print(json.dumps({k: v for k, v in report.items() if k != "trade_log"}, indent=2))

    out = args.output if os.path.isabs(args.output) else os.path.join(APP_DIR, args.output)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"💾 {out}")
    sys.exit(0 if report.get("pass_gate") else 1)


if __name__ == "__main__":
    main()
