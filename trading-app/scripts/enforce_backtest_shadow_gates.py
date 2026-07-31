#!/usr/bin/env python3
"""Ensure strategies that fail Fyers backtest gates stay in shadow (paper) mode."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import pytz

IST = pytz.timezone("Asia/Kolkata")

GATE_REPORTS = (
    ("reports/orb_fyers_backtest.json", "Strategy 3: 5-Minute ORB"),
    ("reports/s9_fyers_backtest.json", "Strategy 9: 9-EMA Momentum Scalper"),
)


def strategies_failing_gate(app_dir: str) -> list[str]:
    failed: list[str] = []
    for rel, strategy in GATE_REPORTS:
        path = os.path.join(app_dir, rel)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if not data.get("pass_gate", False):
            failed.append(strategy)
    return failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Shadow strategies that fail backtest gates")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--app-dir", default=".")
    parser.add_argument("--state-dir", default="logs")
    args = parser.parse_args()

    app_dir = os.path.abspath(args.app_dir)
    failed = strategies_failing_gate(app_dir)
    if not failed:
        print("✅ All backtest gate reports pass (or missing) — no shadow enforcement needed.")
        return 0

    state_path = os.path.join(args.state_dir, f"trading_state_{args.user_id}.json")
    if not os.path.isfile(state_path):
        print(f"❌ State file not found: {state_path}")
        return 1

    until = (datetime.now(IST).date() + timedelta(days=args.days)).isoformat()
    with open(state_path, encoding="utf-8") as f:
        data = json.load(f)

    shadow = list(data.get("shadow_strategies") or [])
    for s in failed:
        if s not in shadow:
            shadow.append(s)
    data["shadow_strategies"] = shadow
    data["shadow_week_until"] = max(data.get("shadow_week_until") or "", until)

    tmp = state_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, state_path)

    print(f"✅ Shadow enforced until {data['shadow_week_until']} for user {args.user_id}")
    for s in failed:
        print(f"   👻 {s} (pass_gate=false)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
