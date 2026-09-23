"""Unit tests for shared ORB entry filters."""
from datetime import datetime

import pytz

from engine.orb_filters import (
    MAX_ORB_RANGE_PCT,
    MIN_ORB_RANGE_PCT,
    aggregate_15m_from_5m,
    is_index_spot_symbol,
    orb_range_ok,
    passes_volume_check,
    trend_15m_confirms,
    volume_filter_enabled,
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
    ok, pct = orb_range_ok(100.15, 100.00, 100.00)  # 0.15% — inside 0.10–0.40
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


def test_volume_filter_disabled_for_index_symbol():
    dense = [_candle(15 + i * 5, 100, 101, 99, 100, vol=50000.0) for i in range(8)]
    assert volume_filter_enabled("NSE:NIFTY50-INDEX", dense) is False
    assert passes_volume_check(1, 1000, 16.0, symbol="NSE:NIFTY50-INDEX", candles_5m=dense) is True
    assert volume_filter_enabled("NSE:RELIANCE-EQ", dense) is True


def test_is_index_spot_symbol():
    assert is_index_spot_symbol("NSE:NIFTY50-INDEX") is True
    assert is_index_spot_symbol("NSE:RELIANCE-EQ") is False


# --- Strategy 3 (5-Min ORB) call-site evaluation-window gate -------------------
# Tightened 23-09-26 for 55% WR quality: window ends at 10:00 (was 10:30).


def test_strat3_orb_window_admits_morning_times():
    """Times inside 09:20–10:00 are admitted; past 10:00 rejected."""
    from workers.auto_trader import _strat3_orb_window_ok

    assert _strat3_orb_window_ok("09:45:00") is True
    assert _strat3_orb_window_ok("09:55:00") is True
    assert _strat3_orb_window_ok("10:15:00") is False


def test_strat3_orb_window_boundaries():
    """Boundary discipline: inclusive at 09:20 and 10:00, rejects just outside."""
    from workers.auto_trader import _strat3_orb_window_ok

    assert _strat3_orb_window_ok("09:15:00") is False
    assert _strat3_orb_window_ok("10:05:00") is False
    assert _strat3_orb_window_ok("09:20:00") is True
    assert _strat3_orb_window_ok("10:00:00") is True
    assert _strat3_orb_window_ok("10:30:00") is False
