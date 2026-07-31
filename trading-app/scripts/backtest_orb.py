#!/usr/bin/env python3
"""
Backtest Strategy 3: 5-Minute ORB on NIFTY spot (yfinance proxy).

Mirrors live checklist: ORB range from 9:15 candle, VIX-adaptive entry mode (simulated),
adaptive volume (2.5× low-VIX / 2× high-VIX), 15m trend alignment, gap < 1%,
ORB range 0.08%–0.5%, economic blackout days. Filters live in engine/orb_filters.py.

Usage:
  cd trading-app && .venv/bin/python scripts/backtest_orb.py --days 59
  cd trading-app && .venv/bin/python scripts/backtest_orb.py --days 59 --output reports/orb_backtest.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pytz

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, APP_DIR)

IST = pytz.timezone("Asia/Kolkata")

from engine.economic_calendar import check_no_economic_events
from engine.orb_filters import orb_range_ok, trend_15m_confirms, volume_multiplier


def fetch_candles(symbol: str, days: int) -> Tuple[List[Dict], List[Dict]]:
    try:
        import yfinance as yf
    except ImportError:
        print("❌ yfinance required: pip install yfinance")
        sys.exit(1)
    ticker = yf.Ticker(symbol)
    df_5m = ticker.history(period=f"{days}d", interval="5m")
    df_daily = ticker.history(period="1y", interval="1d")
    if df_5m.empty or df_daily.empty:
        return [], []

    if df_5m.index.tz is None:
        df_5m.index = df_5m.index.tz_localize("UTC").tz_convert(IST)
    else:
        df_5m.index = df_5m.index.tz_convert(IST)

    candles_5m = []
    for ts, row in df_5m.iterrows():
        candles_5m.append({
            "timestamp": int(ts.timestamp()),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": float(row.get("Volume", 0) or 0),
        })

    candles_daily = []
    for ts, row in df_daily.iterrows():
        candles_daily.append({
            "timestamp": int(ts.timestamp()),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
        })
    return candles_5m, candles_daily


def group_by_session_day(candles_5m: List[Dict]) -> Dict[str, List[Dict]]:
    days: Dict[str, List[Dict]] = {}
    for c in candles_5m:
        dt = datetime.fromtimestamp(c["timestamp"], IST)
        key = dt.strftime("%Y-%m-%d")
        days.setdefault(key, []).append(c)
    for key in days:
        days[key].sort(key=lambda x: x["timestamp"])
    return days


def simulate_exit(entry: float, direction: str, sl_pts: float, tp_pts: float, future: List[Dict]) -> Tuple[str, float]:
    if direction == "LONG":
        sl, tp = entry - sl_pts, entry + tp_pts
        for c in future:
            if c["low"] <= sl:
                return "LOSS", -sl_pts
            if c["high"] >= tp:
                return "WIN", tp_pts
        if future:
            last = future[-1]["close"]
            return ("WIN", last - entry) if last > entry else ("LOSS", last - entry)
    else:
        sl, tp = entry + sl_pts, entry - tp_pts
        for c in future:
            if c["high"] >= sl:
                return "LOSS", -sl_pts
            if c["low"] <= tp:
                return "WIN", tp_pts
        if future:
            last = future[-1]["close"]
            return ("WIN", entry - last) if last < entry else ("LOSS", entry - last)
    return "LOSS", 0.0


def backtest_orb(
    candles_5m: List[Dict],
    candles_daily: List[Dict],
    vix_assumption: float = 16.0,
    sl_pts: float = 20.0,
    tp_pts: float = 40.0,
) -> Dict:
    days = group_by_session_day(candles_5m)
    trades: List[Dict] = []
    skips: Dict[str, int] = {
        "blackout": 0,
        "window": 0,
        "volume": 0,
        "gap": 0,
        "range": 0,
        "trend": 0,
        "no_breakout": 0,
    }

    sorted_days = sorted(days.keys())
    for day_str in sorted_days:
        if not check_no_economic_events(day_str):
            skips["blackout"] += 1
            continue

        daily = days[day_str]
        if not daily:
            continue

        first = daily[0]
        dt0 = datetime.fromtimestamp(first["timestamp"], IST)
        if not (dt0.hour == 9 and dt0.minute == 15):
            continue

        orb_high, orb_low, orb_open = first["high"], first["low"], first["open"]
        if orb_open <= 0:
            continue

        ok_range, range_pct = orb_range_ok(orb_high, orb_low, orb_open)
        if not ok_range:
            skips["range"] += 1
            continue

        # Gap vs previous daily close
        prev_daily = [c for c in candles_daily if datetime.fromtimestamp(c["timestamp"], IST).strftime("%Y-%m-%d") < day_str]
        if prev_daily:
            prev_close = prev_daily[-1]["close"]
            gap_pct = abs(orb_open - prev_close) / prev_close * 100
            if gap_pct >= 1.0:
                skips["gap"] += 1
                continue

        prev_920_vols = []
        for c in candles_5m:
            cdt = datetime.fromtimestamp(c["timestamp"], IST)
            if cdt.strftime("%Y-%m-%d") < day_str and cdt.hour == 9 and cdt.minute == 20:
                prev_920_vols.append(c["volume"])

        triggered = False
        for i, c in enumerate(daily):
            cdt = datetime.fromtimestamp(c["timestamp"], IST)
            t = cdt.strftime("%H:%M:%S")
            if t < "09:20:00" or t > "10:30:00":
                continue

            direction = None
            trigger_close = c["close"]
            trigger_vol = c["volume"]

            if vix_assumption > 15.0:
                if trigger_close > orb_high:
                    direction = "LONG"
                elif trigger_close < orb_low:
                    direction = "SHORT"
            else:
                if t >= "09:25:00" and trigger_close > orb_high:
                    direction = "LONG"
                elif t >= "09:25:00" and trigger_close < orb_low:
                    direction = "SHORT"

            if not direction:
                continue

            if prev_920_vols:
                avg_vol = sum(prev_920_vols) / len(prev_920_vols)
            else:
                all_v = [x["volume"] for x in candles_5m if x["volume"] > 0]
                avg_vol = sum(all_v) / len(all_v) if all_v else 1.0

            vol_mult = volume_multiplier(vix_assumption)
            if trigger_vol < vol_mult * avg_vol:
                skips["volume"] += 1
                continue

            bullish = direction == "LONG"
            candles_so_far = daily[: i + 1]
            if not trend_15m_confirms(candles_so_far, bullish=bullish):
                skips["trend"] += 1
                continue

            outcome, pnl = simulate_exit(trigger_close, direction, sl_pts, tp_pts, daily[i + 1 :])
            trades.append({
                "date": day_str,
                "direction": direction,
                "entry": round(trigger_close, 2),
                "outcome": outcome,
                "pnl_pts": round(pnl, 2),
                "orb_range_pct": round(range_pct, 3),
            })
            triggered = True
            break

        if not triggered:
            skips["no_breakout"] += 1

    wins = sum(1 for t in trades if t["outcome"] == "WIN")
    losses = len(trades) - wins
    total_pnl = sum(t["pnl_pts"] for t in trades)
    gross_win = sum(t["pnl_pts"] for t in trades if t["pnl_pts"] > 0)
    gross_loss = abs(sum(t["pnl_pts"] for t in trades if t["pnl_pts"] < 0))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)

    return {
        "strategy": "Strategy 3: 5-Minute ORB",
        "sessions": len(sorted_days),
        "trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round((wins / len(trades) * 100) if trades else 0, 1),
        "profit_factor": round(pf, 2),
        "total_pnl_pts": round(total_pnl, 1),
        "pass_gate": (wins / len(trades) >= 0.45 and pf >= 1.3) if trades else False,
        "skips": skips,
        "trade_log": trades,
    }


def main():
    parser = argparse.ArgumentParser(description="Backtest Strategy 3 ORB")
    parser.add_argument("--symbol", default="^NSEI")
    parser.add_argument("--days", type=int, default=59)
    parser.add_argument("--vix", type=float, default=16.0)
    parser.add_argument("--output", default="")
    parser.add_argument("--dry-run", action="store_true", help="Fetch data only")
    args = parser.parse_args()

    print(f"📊 Fetching {args.days}d 5m data for {args.symbol}...")
    c5, cd = fetch_candles(args.symbol, args.days)
    if not c5:
        print("❌ No data")
        sys.exit(1)
    print(f"✅ {len(c5)} 5m candles loaded")

    if args.dry_run:
        sys.exit(0)

    report = backtest_orb(c5, cd, vix_assumption=args.vix)
    print(json.dumps({k: v for k, v in report.items() if k != "trade_log"}, indent=2))

    if args.output:
        out_path = args.output if os.path.isabs(args.output) else os.path.join(APP_DIR, args.output)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"💾 Report saved: {out_path}")

    sys.exit(0 if report.get("pass_gate") else 1)


if __name__ == "__main__":
    main()
