#!/usr/bin/env python3
"""
Strategy 9 shadow comparison — rules-only baseline (+ optional LLM mode).

Usage:
  cd trading-app
  .venv/bin/python scripts/backtest_strategy9_shadow.py --days 59 --mode rules-only
  .venv/bin/python scripts/backtest_strategy9_shadow.py --days 30 --mode llm   # needs AI key
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Dict, List

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, APP_DIR)
sys.path.insert(0, SCRIPT_DIR)

from backtest_strategy9_rules import fetch_5m, run_backtest  # noqa: E402


def summarize_rules(report: Dict) -> Dict:
    return {
        "mode": "rules-only",
        "trades": report.get("trades", 0),
        "wins": report.get("wins", 0),
        "losses": report.get("losses", 0),
        "win_rate_pct": report.get("win_rate_pct", 0),
        "profit_factor": report.get("profit_factor", 0),
        "pass_gate": report.get("pass_gate", False),
        "false_entry_proxy": report.get("losses", 0),  # rules losses as baseline false entries
    }


def compare_llm_shadow_log(rules_report: Dict, shadow_log_path: str) -> Dict:
    """Compare live LLM shadow JSONL against rules-only false-entry baseline."""
    if not os.path.exists(shadow_log_path):
        return {
            "llm_shadow_available": False,
            "message": f"No shadow log at {shadow_log_path} — run live sessions to populate.",
        }

    rows: List[Dict] = []
    with open(shadow_log_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    would_exec = [r for r in rows if r.get("would_execute")]
    skips = [r for r in rows if not r.get("would_execute")]
    rules_false = max(int(rules_report.get("losses") or 0), 1)
    # Without fill outcomes offline, treat LLM buy-rate vs rules loss count as a rate ratio signal.
    llm_buy_rate = (len(would_exec) / len(rows)) if rows else 0.0
    rules_loss_rate = (rules_report.get("losses", 0) / max(rules_report.get("trades", 1), 1))
    ratio = (llm_buy_rate / rules_loss_rate) if rules_loss_rate else None

    return {
        "llm_shadow_available": True,
        "llm_decisions": len(rows),
        "llm_would_execute": len(would_exec),
        "llm_skips": len(skips),
        "llm_buy_rate": round(llm_buy_rate, 3),
        "rules_loss_rate": round(rules_loss_rate, 3),
        "false_entry_rate_ratio_vs_rules": round(ratio, 3) if ratio is not None else None,
        "pass_shadow_gate": (ratio is not None and ratio <= 2.0),
        "rules_false_entry_proxy": rules_false,
    }


def main():
    parser = argparse.ArgumentParser(description="Strategy 9 shadow backtest")
    parser.add_argument("--symbol", default="^NSEI")
    parser.add_argument("--days", type=int, default=59)
    parser.add_argument("--mode", choices=["rules-only", "llm"], default="rules-only")
    parser.add_argument("--min-adx", type=float, default=None, help="Override MIN_ADX_15M for sweep")
    parser.add_argument("--output", default="reports/strategy9_shadow_rules.json")
    parser.add_argument(
        "--shadow-log",
        default="logs/strategy9_llm_shadow.jsonl",
        help="Live LLM shadow JSONL path for comparison",
    )
    args = parser.parse_args()

    if args.min_adx is not None:
        import engine.strategy9_filters as s9f

        s9f.MIN_ADX_15M = float(args.min_adx)

    if args.mode == "llm":
        # Offline LLM replay of historical bars is not implemented (costly + non-deterministic).
        # We compare any existing live shadow log against a fresh rules-only baseline.
        print("ℹ️  --mode llm uses live shadow JSONL + rules-only baseline (no historical LLM replay).")

    print(f"📊 Fetching {args.days}d for {args.symbol}...")
    candles = fetch_5m(args.symbol, args.days)
    if not candles:
        print("❌ No candle data")
        sys.exit(1)

    rules = run_backtest(candles)
    if args.min_adx is not None:
        rules["strategy"] = f"Strategy 9 rules-only (ADX≥{args.min_adx}, 10:00–14:00)"
        rules["min_adx"] = args.min_adx

    shadow_path = args.shadow_log if os.path.isabs(args.shadow_log) else os.path.join(APP_DIR, args.shadow_log)
    comparison = compare_llm_shadow_log(rules, shadow_path)

    report = {
        "generated_at": datetime.now(tz=__import__("datetime").timezone.utc).isoformat(),
        "mode": args.mode,
        "rules_only": summarize_rules(rules),
        "rules_full": {k: v for k, v in rules.items() if k != "sample_trades"},
        "llm_comparison": comparison,
        "pass_gate": bool(rules.get("pass_gate")),
    }

    out = args.output if os.path.isabs(args.output) else os.path.join(APP_DIR, args.output)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    print(json.dumps(report["rules_only"], indent=2))
    print(json.dumps(report["llm_comparison"], indent=2))
    print(f"💾 {out}")
    # Always exit 0 when the report file is written; gate lives in JSON.
    sys.exit(0)


if __name__ == "__main__":
    main()
