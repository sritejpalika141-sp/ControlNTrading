"""Anti-chase + fade-strategy disable — why one-sided markets still lost."""
import os
import sys
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-prod")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workers.auto_trader import _is_fade_strategy, _is_chase_entry  # noqa: E402
from engine.automation import TradingState  # noqa: E402


def test_fade_strategies_detected():
    assert _is_fade_strategy("Strategy 5: Optimized Aerospace Mean Reversion")
    assert _is_fade_strategy("Strategy 6: Gap Fill Reversal")
    assert not _is_fade_strategy("Strategy 3: 5-Minute ORB")
    assert not _is_fade_strategy("Strategy 1: OB + FVG")


def test_defaults_exclude_fade_strategies():
    st = TradingState(user_id=424242)
    assert "Strategy 5: Optimized Aerospace Mean Reversion" not in st.active_strategies
    assert "Strategy 6: Gap Fill Reversal" not in st.active_strategies


def test_chase_near_local_high():
    candles = [
        {"high": 100, "low": 90, "close": 95},
        {"high": 102, "low": 91, "close": 96},
        {"high": 110, "low": 100, "close": 108},
        {"high": 111, "low": 105, "close": 109},
        {"high": 112, "low": 108, "close": 111},
    ]

    async def _run():
        with patch("workers.auto_trader.api_queue.enqueue", new=AsyncMock(return_value=candles)):
            return await _is_chase_entry(MagicMock(), "NSE:NIFTY1CE", 111.5)

    chase, why = asyncio.get_event_loop().run_until_complete(_run())
    assert chase is True
    assert "high" in why


def test_not_chase_on_pullback():
    candles = [
        {"high": 100, "low": 90, "close": 95},
        {"high": 110, "low": 100, "close": 108},
        {"high": 112, "low": 100, "close": 101},
        {"high": 105, "low": 98, "close": 100},
        {"high": 103, "low": 97, "close": 99},
    ]

    async def _run():
        with patch("workers.auto_trader.api_queue.enqueue", new=AsyncMock(return_value=candles)):
            return await _is_chase_entry(MagicMock(), "NSE:NIFTY1CE", 99.0)

    chase, _ = asyncio.get_event_loop().run_until_complete(_run())
    assert chase is False
