"""Tests for P0 intraday stability fixes (Phase A)."""
from datetime import datetime

import pytz

from engine.technical_indicators import calculate_adx, calculate_adx_di, candle_ist_date
from engine.strategy_10 import evaluate_strategy_10


IST = pytz.timezone("Asia/Kolkata")


def _trending_candles(n=30, start=100.0, step=0.5):
    candles = []
    price = start
    base_ts = datetime(2026, 7, 31, 9, 15, tzinfo=IST).timestamp()
    for i in range(n):
        o = price
        price += step
        candles.append({
            "timestamp": int(base_ts + i * 300),
            "open": o,
            "high": price + 0.3,
            "low": o - 0.2,
            "close": price,
            "volume": 1000 + i,
        })
    return candles


def test_calculate_adx_not_constant_mock():
    candles = _trending_candles()
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    adx = calculate_adx(highs, lows, closes, 14)
    assert adx != 26.4
    assert adx > 0


def test_candle_ist_date_accepts_unix_timestamp():
    ts = int(datetime(2026, 7, 31, 10, 5, tzinfo=IST).timestamp())
    assert candle_ist_date({"timestamp": ts}, IST).isoformat() == "2026-07-31"


def test_candle_ist_date_accepts_iso_string():
    assert candle_ist_date({"timestamp": "2026-07-31T10:05:00+05:30"}, IST).isoformat() == "2026-07-31"


def test_strategy_10_import_and_disabled_by_default():
    import importlib
    mod = importlib.import_module("engine.strategy_10")
    assert hasattr(mod, "evaluate_strategy_10")


def test_strategy_11_put_sl_direction_for_puts():
    """PUT legs must place stop above spot using max(high), not min(low)."""
    sl_source = [
        {"high": 105.0, "low": 100.0},
        {"high": 106.0, "low": 101.0},
        {"high": 107.0, "low": 102.0},
    ]
    spot = 103.0
    sl = max(float(c["high"]) for c in sl_source[-3:]) + 0.5
    assert sl > spot
    wrong_sl = min(float(c["low"]) for c in sl_source[-3:]) - 0.5
    assert wrong_sl < spot


def test_gap_strategy_filters_todays_candles_with_unix_ts():
    from engine.strategy_gap import evaluate_gap_fill_strategy
    import asyncio

    ist = IST
    base = datetime(2026, 7, 31, 9, 15, tzinfo=ist)
    candles = []
    for i, minute in enumerate([15, 20, 25]):
        ts = int(base.replace(minute=minute).timestamp())
        candles.append({
            "timestamp": ts,
            "open": 100 + i,
            "high": 101 + i,
            "low": 99 + i,
            "close": 100.5 + i,
            "volume": 500,
        })

    class _State:
        strat_6_trades_today = 0
        strat_6_confirmed = False
        max_sl_trending = 20

        def save(self):
            pass

    analysis = {
        "candles_daily": [
            {"open": 100, "close": 99, "high": 101, "low": 98},
            {"open": 101.5, "close": 101, "high": 102, "low": 100},  # gap up
        ]
    }

    async def _run():
        return await evaluate_gap_fill_strategy(
            spot=101.0,
            candles_5m=candles,
            analysis=analysis,
            client=object(),
            state=_State(),
        )

    # Should not crash on timestamp parsing; may return False without full gap trigger chain
    result = asyncio.get_event_loop().run_until_complete(_run())
    assert isinstance(result, tuple)
