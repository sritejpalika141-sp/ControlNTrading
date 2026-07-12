"""
Crude EIA-day volatility strategy (multi-asset Phase 2).

Trades the volatility spike around the weekly EIA (US Energy Information Administration) petroleum
inventory report, released Wednesdays ~10:30 AM ET (~20:00 IST in summer). OUTSIDE that Wednesday
window — and on any non-Wednesday — this strategy always emits NO TRADE.

The exact release/window is read from the CRUDE_OIL_OPTIONS registry risk_config ("eia_window"),
so it is tunable without touching this file. ⚠️ The default window is PROVISIONAL — confirm the exact
EIA release-time convention (and IST DST offset) before live-small enablement.

Returns the directional-signal shape consumed by the shared execute path
({"type": "CALL"|"PUT"|"NO TRADE", "side", "strategy", "reason", "confidence", "asset_class"}).
Strike/SL/qty resolution is done downstream by the shared (now asset-class-aware) pipeline — this
module only makes the WHEN + DIRECTION decision, so it slots in without a per-strategy code path.
"""
import logging
from datetime import datetime
import pytz

from engine.asset_classes import get_asset_class

logger = logging.getLogger("CRUDE_EIA")
IST = pytz.timezone("Asia/Kolkata")
_ASSET = "CRUDE_OIL_OPTIONS"
_WEDNESDAY = 2  # Monday=0 ... Wednesday=2


def _no_trade(reason: str) -> dict:
    return {"type": "NO TRADE", "side": None, "strategy": "Crude EIA Volatility",
            "reason": reason, "confidence": 0, "asset_class": _ASSET}


def _in_window(now: datetime, window) -> bool:
    (sh, sm), (eh, em) = window
    start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    return start <= now <= end


def generate_signal(candles=None, now: datetime = None, asset_class: str = _ASSET) -> dict:
    """candles: recent option/underlying candles [{high, low, close}, ...] (most-recent last).
    now: injectable IST datetime for deterministic tests (defaults to live IST now)."""
    if now is None:
        now = datetime.now(IST)

    window = get_asset_class(asset_class).risk_config.get("eia_window", ((19, 30), (21, 0)))

    if now.weekday() != _WEDNESDAY:
        return _no_trade("Not Wednesday — EIA strategy inactive")
    if not _in_window(now, window):
        return _no_trade(f"Outside EIA window {window}")
    if not candles or len(candles) < 3:
        return _no_trade("EIA window active but insufficient candle data")

    # Breakout of the prior-range around the release: close above recent high -> CALL, below low -> PUT.
    prior = candles[:-1]
    last = candles[-1]
    recent_high = max(c["high"] for c in prior)
    recent_low = min(c["low"] for c in prior)
    if last["close"] > recent_high:
        return {"type": "CALL", "side": "BUY", "strategy": "Crude EIA Volatility",
                "reason": "EIA-day upside breakout", "confidence": 88, "asset_class": _ASSET}
    if last["close"] < recent_low:
        return {"type": "PUT", "side": "BUY", "strategy": "Crude EIA Volatility",
                "reason": "EIA-day downside breakout", "confidence": 88, "asset_class": _ASSET}
    return _no_trade("EIA window active but no breakout")
