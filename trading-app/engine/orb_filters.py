"""Shared ORB entry filters — used by live strategy and backtest script."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List

import pytz

from engine.technical_indicators import calculate_ema

IST = pytz.timezone("Asia/Kolkata")

MIN_ORB_RANGE_PCT = 0.08   # skip ultra-tight opening ranges (noise)
MAX_ORB_RANGE_PCT = 0.50

INDEX_SYMBOL_MARKERS = ("NIFTY50-INDEX", "BANKNIFTY-INDEX", "^NSEI", "-INDEX")


def is_index_spot_symbol(symbol: str) -> bool:
    u = (symbol or "").upper()
    return any(m in u for m in INDEX_SYMBOL_MARKERS)


def volume_filter_enabled(symbol: str, candles_5m: List[Dict]) -> bool:
    """
    Return False when volume data is too sparse to compare (common on Fyers index feeds).
  When False, callers should skip the volume gate rather than reject every breakout.
    """
    if not candles_5m:
        return False
    sample = candles_5m[-min(500, len(candles_5m)) :]
    nonzero = sum(1 for c in sample if (c.get("volume") or 0) > 0)
    if nonzero < max(3, int(len(sample) * 0.15)):
        return False
    if is_index_spot_symbol(symbol):
        # Index prints often have volume but not comparable to yfinance equity volume scale.
        med = sorted((c.get("volume") or 0) for c in sample if (c.get("volume") or 0) > 0)
        if med and med[len(med) // 2] < 100:
            return False
    return True


def passes_volume_check(
    trigger_volume: float,
    avg_volume: float,
    vix: float,
    *,
    symbol: str = "",
    candles_5m: List[Dict] | None = None,
) -> bool:
    if not volume_filter_enabled(symbol, candles_5m or []):
        return True
    vol_mult = volume_multiplier(vix)
    return trigger_volume >= vol_mult * avg_volume


def volume_multiplier(vix: float) -> float:
    """Higher bar on low-VIX days where false breakouts are common."""
    return 2.5 if vix <= 15.0 else 2.0


def orb_range_ok(orb_high: float, orb_low: float, orb_open: float) -> tuple[bool, float]:
    if orb_open <= 0:
        return False, 0.0
    range_pct = (orb_high - orb_low) / orb_open * 100
    if range_pct < MIN_ORB_RANGE_PCT:
        return False, range_pct
    if range_pct >= MAX_ORB_RANGE_PCT:
        return False, range_pct
    return True, range_pct


def aggregate_15m_from_5m(candles_5m: List[Dict]) -> List[Dict]:
    """Bucket 5m candles into 15m OHLCV bars (IST session order)."""
    if not candles_5m:
        return []
    buckets: Dict[str, Dict] = {}
    for c in candles_5m:
        dt = datetime.fromtimestamp(c["timestamp"], IST)
        key = dt.strftime("%Y-%m-%d %H:") + f"{(dt.minute // 15) * 15:02d}"
        b = buckets.get(key)
        if not b:
            buckets[key] = {
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": c.get("volume", 0) or 0,
                "timestamp": c["timestamp"],
            }
        else:
            b["high"] = max(b["high"], c["high"])
            b["low"] = min(b["low"], c["low"])
            b["close"] = c["close"]
            b["volume"] += c.get("volume", 0) or 0
    return [buckets[k] for k in sorted(buckets.keys())]


def trend_15m_confirms(candles_5m_today: List[Dict], bullish: bool) -> bool:
    """
    Require completed 15m structure to align with breakout direction.
    Before two 15m bars exist, fall back to first two 5m candles agreeing with direction.
    """
    bars_15 = aggregate_15m_from_5m(candles_5m_today)
    if len(bars_15) >= 2:
        last, prev = bars_15[-1], bars_15[-2]
        closes = [b["close"] for b in bars_15[-4:]]
        ema = calculate_ema(closes, min(3, len(closes)))
        if bullish:
            return last["close"] > last["open"] and last["close"] >= ema and last["close"] >= prev["close"]
        return last["close"] < last["open"] and last["close"] <= ema and last["close"] <= prev["close"]

    if len(candles_5m_today) >= 2:
        c0, c1 = candles_5m_today[0], candles_5m_today[1]
        if bullish:
            return c1["close"] > c0["open"] and c1["close"] > c1["open"]
        return c1["close"] < c0["open"] and c1["close"] < c1["open"]

    return False
