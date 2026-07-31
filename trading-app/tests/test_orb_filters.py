"""Unit tests for shared ORB entry filters."""
from datetime import datetime

import pytz

from engine.orb_filters import (
    MAX_ORB_RANGE_PCT,
    MIN_ORB_RANGE_PCT,
    aggregate_15m_from_5m,
    orb_range_ok,
    trend_15m_confirms,
    volume_multiplier,
)

IST = pytz.timezone("Asia/Kolkata")


def _candle(minute: int, o: float, h: float, l: float, c: float, vol: float = 1000.0):
    base = datetime(2026, 7, 31, 9, 15, tzinfo=IST)
    ts = int(base.replace(minute=minute).timestamp())
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": vol}


def test_volume_multiplier_low_vix_stricter():
    assert volume_multiplier(14.0) == 2.5
    assert volume_multiplier(15.0) == 2.5
    assert volume_multiplier(16.0) == 2.0


def test_orb_range_ok_bounds():
    ok, pct = orb_range_ok(100.10, 100.00, 100.00)
    assert ok is True
    assert MIN_ORB_RANGE_PCT <= pct < MAX_ORB_RANGE_PCT

    ok_narrow, _ = orb_range_ok(100.00, 99.99, 100.00)
    assert ok_narrow is False

    ok_wide, pct_wide = orb_range_ok(100.60, 100.00, 100.00)
    assert ok_wide is False
    assert pct_wide >= MAX_ORB_RANGE_PCT


def test_aggregate_15m_from_5m():
    candles = [_candle(15, 100, 101, 99, 100.5), _candle(20, 100.5, 102, 100, 101.5)]
    bars = aggregate_15m_from_5m(candles)
    assert len(bars) == 1
    assert bars[0]["high"] == 102
    assert bars[0]["low"] == 99


def test_trend_15m_confirms_bullish_with_two_5m_candles():
    candles = [
        _candle(15, 100, 101, 99.5, 100.5),
        _candle(20, 100.5, 102, 100, 101.5),
    ]
    assert trend_15m_confirms(candles, bullish=True) is True
    assert trend_15m_confirms(candles, bullish=False) is False


def test_trend_15m_confirms_bearish_with_two_5m_candles():
    candles = [
        _candle(15, 100, 100.5, 99, 99.5),
        _candle(20, 99.5, 99.8, 98, 98.5),
    ]
    assert trend_15m_confirms(candles, bullish=False) is True
    assert trend_15m_confirms(candles, bullish=True) is False
