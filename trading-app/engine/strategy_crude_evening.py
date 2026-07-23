"""
Crude evening-session momentum strategy (multi-asset Phase 2).

Active only after ~17:00 IST (the US pre-market/open linkage window, when crude tracks its
international move most strongly). Outside that window it always emits NO TRADE.

Window start is read from the CRUDE_OIL_OPTIONS registry risk_config ("evening_session_start"),
and the session must still be open (before the crude hard-exit). Returns the directional-signal
shape consumed by the shared execute path; strike/SL/qty resolution is downstream.
"""
import logging
from datetime import datetime
import pytz

from engine.asset_classes import get_asset_class

logger = logging.getLogger("CRUDE_EVENING")
IST = pytz.timezone("Asia/Kolkata")
_ASSET = "CRUDE_OIL_OPTIONS"


def _no_trade(reason: str) -> dict:
    return {"type": "NO TRADE", "side": None, "strategy": "Crude Evening Momentum",
            "reason": reason, "confidence": 0, "asset_class": _ASSET}


def generate_signal(candles=None, now: datetime = None, asset_class: str = _ASSET) -> dict:
    """candles: recent momentum candles [{high, low, close}, ...] (most-recent last).
    now: injectable IST datetime for deterministic tests."""
    if now is None:
        now = datetime.now(IST)

    ac = get_asset_class(asset_class)
    heh, hem = ac.hard_exit_time
    hard_exit = now.replace(hour=heh, minute=hem, second=0, microsecond=0)

    # Per owner directive (22-07-26): this momentum strategy now runs the FULL MCX session, not
    # only the post-17:00 evening window. The 17:00 lower-bound gate has been removed. The
    # hard-exit upper bound is kept — it is a safety rail (no new entries right before the
    # mandatory session close), not a strategy-identity gate.
    if now >= hard_exit:
        return _no_trade("Past crude hard-exit — no new entries")
    if not candles or len(candles) < 3:
        return _no_trade("Insufficient candle data")

    # Momentum continuation: three consecutive higher/lower closes -> ride the move.
    closes = [c["close"] for c in candles[-3:]]
    if closes[0] < closes[1] < closes[2]:
        return {"type": "CALL", "side": "BUY", "strategy": "Crude Evening Momentum",
                "reason": "Upside momentum continuation", "confidence": 86, "asset_class": _ASSET}
    if closes[0] > closes[1] > closes[2]:
        return {"type": "PUT", "side": "BUY", "strategy": "Crude Evening Momentum",
                "reason": "Downside momentum continuation", "confidence": 86, "asset_class": _ASSET}
    return _no_trade("No clear momentum")
