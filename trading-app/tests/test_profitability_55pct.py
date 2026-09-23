"""55% WR profitability pack — confluence S1, hindsight wiring, S10 fade-off, gates."""
import asyncio
import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytz

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-prod")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

IST = pytz.timezone("Asia/Kolkata")


def test_strat1_confluence_only_flag():
    import ast
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "engine" / "signals.py"
    tree = ast.parse(src.read_text())
    found = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "STRAT1_CONFLUENCE_ONLY":
                    found = node.value
    assert found is not None
    assert isinstance(found, ast.Constant) and found.value is True


def test_chase_threshold_uses_hindsight_buffer():
    from engine.profitability_gates import chase_threshold_multiplier
    assert abs(chase_threshold_multiplier(1.0) - 0.990) < 1e-9
    assert abs(chase_threshold_multiplier(0.8) - 0.992) < 1e-9


def test_passes_confidence_floor():
    from engine.profitability_gates import passes_confidence_floor
    ok, _ = passes_confidence_floor({"confidence": 75}, 70)
    assert ok is True
    bad, why = passes_confidence_floor({"confidence": 55}, 70)
    assert bad is False
    assert "55" in why


def test_s9_session_ends_at_1330():
    from engine.strategy9_filters import session_allows_entry, SESSION_END_HOUR, SESSION_END_MINUTE
    assert SESSION_END_HOUR == 13 and SESSION_END_MINUTE == 30
    mid = IST.localize(datetime(2026, 9, 23, 12, 0))
    late = IST.localize(datetime(2026, 9, 23, 13, 45))
    assert session_allows_entry(mid) is True
    assert session_allows_entry(late) is False


def test_orb_range_bounds_tightened():
    from engine.orb_filters import MIN_ORB_RANGE_PCT, MAX_ORB_RANGE_PCT, orb_range_ok
    assert MIN_ORB_RANGE_PCT == 0.10
    assert MAX_ORB_RANGE_PCT == 0.40
    # 0.45% was previously OK at MAX=0.50 — now rejected
    ok, pct = orb_range_ok(100.45, 100.00, 100.00)
    assert pct >= 0.40
    assert ok is False


def test_chase_with_default_1pct_buffer():
    from workers.auto_trader import _is_chase_entry
    candles = [
        {"high": 100, "low": 90, "close": 95},
        {"high": 102, "low": 91, "close": 96},
        {"high": 110, "low": 100, "close": 108},
        {"high": 111, "low": 105, "close": 109},
        {"high": 112, "low": 108, "close": 111},
    ]

    async def _run():
        with patch("workers.auto_trader.api_queue.enqueue", new=AsyncMock(return_value=candles)):
            return await _is_chase_entry(MagicMock(), "NSE:NIFTY1CE", 111.5, chase_buffer_pct=1.0)

    chase, why = asyncio.run(_run())
    assert chase is True
    assert "1.0%" in why or "buffer" in why


def test_strategy10_source_disables_choppy_path():
    src = open(
        os.path.join(os.path.dirname(__file__), "..", "engine", "strategy_10.py")
    ).read()
    assert "mean-reversion path disabled" in src
    assert "RSI Oversold" not in src or "CHOPPY MEAN-REVERSION DISABLED" in src
