"""
Strategy 10: Adaptive ADX Engine

Trend-following intraday entries when ADX confirms directional strength and price aligns with
the 9 EMA on 5-minute candles. Complements ORB / swing strategies with a mid-session trend leg.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Tuple

import pytz

from engine.technical_indicators import calculate_adx_di, calculate_ema

IST = pytz.timezone("Asia/Kolkata")
STRATEGY_NAME = "Strategy 10: Adaptive ADX Engine"
ADX_TREND_MIN = 22.0
ADX_STRONG_MIN = 30.0


async def evaluate_strategy_10(
    symbol: str,
    spot: float,
    candles_5m: List[Dict],
    analysis: Dict,
    client,
    state,
) -> Tuple[bool, Dict]:
    if STRATEGY_NAME not in getattr(state, "active_strategies", []):
        return False, {}

    if len(candles_5m) < 20:
        return False, {}

    now = datetime.now(IST)
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        return False, {}
    if now.hour > 14 or (now.hour == 14 and now.minute > 30):
        return False, {}

    if getattr(state, "strat_10_trades_today", 0) >= 2:
        return False, {}

    highs = [float(c["high"]) for c in candles_5m]
    lows = [float(c["low"]) for c in candles_5m]
    closes = [float(c["close"]) for c in candles_5m]
    di = calculate_adx_di(highs, lows, closes, 14)
    adx = di["adx"]
    if adx < ADX_TREND_MIN:
        return False, {}

    ema9 = calculate_ema(closes, 9)
    last_close = closes[-1]
    regime = "STRONG_TREND" if adx >= ADX_STRONG_MIN else "TRENDING"

    signal_type = None
    if di["plus_di"] > di["minus_di"] and last_close > ema9:
        signal_type = "CALL"
    elif di["minus_di"] > di["plus_di"] and last_close < ema9:
        signal_type = "PUT"

    if not signal_type:
        return False, {}

    sl_points = getattr(state, "max_sl_trending", 25)
    signal = {
        "strategy": STRATEGY_NAME,
        "type": signal_type,
        "side": "BUY",
        "confidence": 88 if adx >= ADX_STRONG_MIN else 82,
        "entry_price": spot,
        "sl_points": sl_points,
        "target_points": sl_points * 2,
        "metadata": {
            "regime": regime,
            "adx": adx,
            "plus_di": di["plus_di"],
            "minus_di": di["minus_di"],
            "ema9": ema9,
        },
    }
    state.strat_10_trades_today = getattr(state, "strat_10_trades_today", 0) + 1
    state.save()
    return True, signal
