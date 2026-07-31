#!/usr/bin/env python3
"""Enable 7-day shadow (paper) execution for ORB + S9 on a user trading state file."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import pytz

IST = pytz.timezone("Asia/Kolkata")
SHADOW_STRATEGIES = [
    "Strategy 3: 5-Minute ORB",
    "Strategy 9: 9-EMA Momentum Scalper",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Enable ORB+S9 shadow week on trading state")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--state-dir", default="logs")
    args = parser.parse_args()

    state_path = os.path.join(args.state_dir, f"trading_state_{args.user_id}.json")
    if not os.path.isfile(state_path):
        print(f"❌ State file not found: {state_path}")
        return 1

    until = (datetime.now(IST).date() + timedelta(days=args.days)).isoformat()
    with open(state_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["shadow_strategies"] = SHADOW_STRATEGIES
    data["shadow_week_until"] = until

    tmp = state_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, state_path)

    print(f"✅ Shadow week enabled for user {args.user_id} until {until}")
    print(f"   Strategies: {', '.join(SHADOW_STRATEGIES)}")
    print(f"   State: {state_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
