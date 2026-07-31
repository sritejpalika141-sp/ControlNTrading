"""Tests for engine/execution_gates.py."""
from engine.execution_gates import passes_microstructure_spread, passes_mtf_alignment


def _candles_bullish_5m(n: int = 12, start: float = 100.0) -> list:
    out = []
    for i in range(n):
        close = start + i * 2.0
        out.append(
            {
                "open": close - 1,
                "high": close + 1,
                "low": close - 2,
                "close": close,
                "volume": 1000,
            }
        )
    return out


def _candles_bearish_5m(n: int = 12, start: float = 200.0) -> list:
    out = []
    for i in range(n):
        close = start - i * 2.0
        out.append(
            {
                "open": close + 1,
                "high": close + 2,
                "low": close - 1,
                "close": close,
                "volume": 1000,
            }
        )
    return out


def test_microstructure_rejects_wide_spread():
    ok, reason = passes_microstructure_spread({"bid": 90.0, "ask": 110.0, "lp": 100.0})
    assert ok is False
    assert "spread" in reason.lower()


def test_microstructure_passes_tight_spread():
    ok, _ = passes_microstructure_spread({"bid": 99.0, "ask": 100.5, "lp": 100.0})
    assert ok is True


def test_microstructure_missing_quotes_passes():
    ok, reason = passes_microstructure_spread({"lp": 50.0})
    assert ok is True
    assert "unvetted" in reason.lower() or "unavailable" in reason.lower()


def test_mtf_call_requires_bullish():
    ok, _ = passes_mtf_alignment(_candles_bullish_5m(), "CALL")
    assert ok is True
    ok, reason = passes_mtf_alignment(_candles_bearish_5m(), "CALL")
    assert ok is False
    assert "blocks CALL" in reason


def test_mtf_put_requires_bearish():
    ok, _ = passes_mtf_alignment(_candles_bearish_5m(), "PUT")
    assert ok is True
    ok, reason = passes_mtf_alignment(_candles_bullish_5m(), "PUT")
    assert ok is False
    assert "blocks PUT" in reason


def test_mtf_insufficient_candles_skips():
    ok, reason = passes_mtf_alignment([], "CALL")
    assert ok is True
    assert "skipped" in reason.lower()
