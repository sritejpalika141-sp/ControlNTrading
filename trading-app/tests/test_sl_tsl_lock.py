"""LOCKED owner rule: SL and TSL are identical for every strategy — last 3×1m option lows.

These are source-contract tests so strategy-specific trail overrides cannot sneak back in.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTO = (ROOT / "workers" / "auto_trader.py").read_text(encoding="utf-8")
GUARD = (ROOT / "workers" / "sl_guardian.py").read_text(encoding="utf-8")


def test_canonical_constants_present():
    assert "CANONICAL_SL_LOOKBACK = 3" in AUTO
    assert 'CANONICAL_SL_RESOLUTION = "1"' in AUTO
    assert "LOCKED OWNER RULE" in AUTO


def test_no_strategy1_variant_l_trail():
    assert "Variant L" not in AUTO or "no Variant-L" in AUTO
    assert "s1_peak_fav" not in AUTO
    assert "Strategy 1 SL →" not in AUTO


def test_no_s3_breakeven_trail_or_skip_global():
    assert "Trailing SL to breakeven" not in AUTO
    assert "SL trailed to breakeven" not in AUTO
    # The old S3/S9 block ended with an unconditional `continue` that skipped global TSL.
    # After T2 exit we still `continue`, but the skip-all-trail path is gone — assert the
    # comment documenting removal is present and FVL/ATR trail strings are gone.
    assert "unconditional continue REMOVED" in AUTO or "T1 breakeven trail" in AUTO
    assert "Activating ATR trail" not in AUTO
    assert "Strategy 5 Trailed SL" not in AUTO


def test_direct_option_path_uses_smart_sl_not_signal_points():
    # Direct-option block must call calculate_smart_sl and must not assign from sig.sl_points
    assert "uses calculate_smart_sl (last-3×1m option low). Signal sl_points are ignored." in AUTO
    assert 'sl_points = sig.get("sl_points"' not in AUTO


def test_strategy1_no_minus2_vix_clamp():
    assert "lowest low of last 3 candles minus 2" not in AUTO
    assert "floored 10 / capped 20" not in AUTO
    assert "CANONICAL SL:" in AUTO


def test_guardian_no_12pct_floor():
    assert "0.12" not in GUARD or "entry * 0.12" not in GUARD
    assert "entry * 0.03" in GUARD
    assert "12%-of-premium" not in GUARD
