"""Initial SL must be last-3 one-min candle low — not a widened % premium floor."""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-prod")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workers.auto_trader import calculate_smart_sl  # noqa: E402


def _c(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c, "volume": 10}


def test_smart_sl_uses_exact_3_candle_1m_low_not_12pct_floor():
    """Regression: crude PE @ 292.9 used to get ~35pt SL (12% floor). Must use 3×1m low."""
    entry = 292.9
    candles = [
        _c(290, 295, 288, 292),
        _c(292, 296, 290, 294),
        _c(294, 297, 291, 293),  # 3-candle low = 288 → dist 4.9
    ]
    client = MagicMock()

    async def _run():
        with patch("workers.auto_trader.api_queue.enqueue", new=AsyncMock(return_value=candles)):
            return await calculate_smart_sl("MCX:CRUDEOIL26AUG7400PE", entry, "BEARISH", client)

    res = asyncio.get_event_loop().run_until_complete(_run())
    assert res["method"] == "3_candle_1m_low"
    assert abs(res["sl_points"] - (entry - 288.0)) < 0.01
    # Must NOT be the old 12% floor (~35.15)
    assert res["sl_points"] < 20


def test_smart_sl_ignores_wider_5_candle_low_when_3_is_valid():
    entry = 100.0
    candles = [
        _c(80, 85, 70, 82),   # older — must NOT pull SL to 70
        _c(90, 95, 88, 92),
        _c(92, 96, 90, 94),
        _c(94, 97, 91, 95),
        _c(95, 98, 93, 96),
    ]
    # last 3 lows: 90, 91, 93 → low 90 → dist 10

    async def _run():
        with patch("workers.auto_trader.api_queue.enqueue", new=AsyncMock(return_value=candles)):
            return await calculate_smart_sl("NSE:NIFTY1CE", entry, "BULLISH", MagicMock())

    res = asyncio.get_event_loop().run_until_complete(_run())
    assert res["method"] == "3_candle_1m_low"
    assert abs(res["sl_points"] - 10.0) < 0.01
