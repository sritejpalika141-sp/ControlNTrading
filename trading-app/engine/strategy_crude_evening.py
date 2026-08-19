"""
Crude evening-session momentum strategy (multi-asset Phase 2).

Active only after ~17:00 IST (the US pre-market/open linkage window, when crude tracks its
international move most strongly). Outside that window it always emits NO TRADE.

Window start is read from the COMMODITY_OPTIONS registry risk_config ("evening_session_start"),
and the session must still be open (before the crude hard-exit). Returns the directional-signal
shape consumed by the shared execute path; strike/SL/qty resolution is downstream.
"""
import logging
from datetime import datetime
import pytz

from engine.asset_classes import get_asset_class

logger = logging.getLogger("CRUDE_EVENING")
IST = pytz.timezone("Asia/Kolkata")
_ASSET = "COMMODITY_OPTIONS"

# 03-08-26 fix: pure 3-candle momentum-continuation entries were buying right after the move had
# already happened (near the extreme), which loses hard on the frequent choppy/range-bound crude
# sessions — a real 3-candle continuation move is only meaningful relative to how noisy the recent
# tape already is. CHOP_ATR_MULT requires the move to be at least this many times the recent
# average candle range (a simple ATR proxy) before it counts as a real signal, not noise.
CHOP_ATR_LOOKBACK = 10
CHOP_ATR_MULT = 0.8


def _no_trade(reason: str) -> dict:
    return {"type": "NO TRADE", "side": None, "strategy": "Crude Evening Momentum",
            "reason": reason, "confidence": 0, "asset_class": _ASSET}


def _passes_chop_filter(candles) -> bool:
    """True if the 3-candle move is large relative to recent volatility (a real move, not chop)."""
    lookback = candles[-(3 + CHOP_ATR_LOOKBACK):-3]
    if len(lookback) < 3:
        return True  # not enough history yet to judge chop — don't block on data scarcity
    atr = sum(c["high"] - c["low"] for c in lookback) / len(lookback)
    if atr <= 0:
        return True
    move = abs(candles[-1]["close"] - candles[-3]["close"])
    return move >= CHOP_ATR_MULT * atr


def generate_signal(candles=None, now: datetime = None, asset_class: str = _ASSET) -> dict:
    """candles: recent momentum candles [{high, low, close}, ...] (most-recent last).
    now: injectable IST datetime for deterministic tests."""
    if now is None:
        now = datetime.now(IST)

    ac = get_asset_class(asset_class)
    heh, hem = ac.hard_exit_time
    hard_exit = now.replace(hour=heh, minute=hem, second=0, microsecond=0)

    # Restored (03-08-26): evening momentum only after 17:00 IST — all-day momentum
    # continuation was chasing moves (buy-high). Hard-exit upper bound still applies.
    try:
        start_hm = (getattr(ac, "risk_config", None) or {}).get("evening_session_start") or (17, 0)
        if isinstance(start_hm, str):
            parts = start_hm.split(":")
            sh, sm = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        else:
            sh, sm = int(start_hm[0]), int(start_hm[1])
        evening_start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        if now < evening_start:
            return _no_trade(f"Before evening window ({sh:02d}:{sm:02d} IST)")
    except Exception:
        if now.hour < 17:
            return _no_trade("Before evening window (17:00 IST)")

    if now >= hard_exit:
        return _no_trade("Past crude hard-exit — no new entries")
    if not candles or len(candles) < 3:
        return _no_trade("Insufficient candle data")

    # Momentum continuation: three consecutive higher/lower closes -> ride the move.
    closes = [c["close"] for c in candles[-3:]]
    if closes[0] < closes[1] < closes[2]:
        if not _passes_chop_filter(candles):
            return _no_trade("Upside momentum too small vs recent range (chop filter)")
        return {"type": "CALL", "side": "BUY", "strategy": "Crude Evening Momentum",
                "reason": "Upside momentum continuation", "confidence": 86, "asset_class": _ASSET}
    if closes[0] > closes[1] > closes[2]:
        if not _passes_chop_filter(candles):
            return _no_trade("Downside momentum too small vs recent range (chop filter)")
        return {"type": "PUT", "side": "BUY", "strategy": "Crude Evening Momentum",
                "reason": "Downside momentum continuation", "confidence": 86, "asset_class": _ASSET}
    return _no_trade("No clear momentum")
