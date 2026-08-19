"""Buy-high entry path must stay disabled; crude strategies must respect session windows."""
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-prod")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.strategy_crude_eia import generate_signal as eia_signal  # noqa: E402
from engine.strategy_crude_evening import generate_signal as evening_signal  # noqa: E402


def _c(h, l, c):
    return {"high": h, "low": l, "close": c, "open": c, "volume": 1}


def test_eia_blocked_on_monday():
    mon = datetime(2026, 8, 3, 20, 0)  # Monday
    candles = [_c(100, 90, 95), _c(101, 91, 96), _c(110, 95, 108)]  # breakout
    sig = eia_signal(candles=candles, now=mon)
    assert sig["type"] == "NO TRADE"
    assert "Wednesday" in sig["reason"] or "Not Wednesday" in sig["reason"]


def test_eia_allows_wednesday_in_window_breakout():
    wed = datetime(2026, 8, 5, 20, 0)  # Wednesday 20:00
    candles = [_c(100, 90, 95), _c(101, 91, 96), _c(110, 95, 108)]
    sig = eia_signal(candles=candles, now=wed)
    assert sig["type"] == "CALL"


def test_evening_blocked_before_1700():
    day = datetime(2026, 8, 3, 14, 0)
    candles = [_c(1, 1, 1), _c(2, 2, 2), _c(3, 3, 3)]
    sig = evening_signal(candles=candles, now=day)
    assert sig["type"] == "NO TRADE"
    assert "evening" in sig["reason"].lower() or "Before" in sig["reason"]


def test_no_candle_high_entry_in_auto_trader():
    src = open(
        os.path.join(os.path.dirname(__file__), "..", "workers", "auto_trader.py"),
        encoding="utf-8",
    ).read()
    assert 'entry_price = opt_candles[-1]["high"]' not in src
    assert "buy-high disabled" in src or "NEVER buy at candle HIGH" in src
    assert 'symbol.startswith(("MCX:", "CDS:"))' in src


def test_signals_flag_off():
    src = open(
        os.path.join(os.path.dirname(__file__), "..", "engine", "signals.py"),
        encoding="utf-8",
    ).read()
    assert '"use_1m_option_candle": False' in src or "'use_1m_option_candle': False" in src
