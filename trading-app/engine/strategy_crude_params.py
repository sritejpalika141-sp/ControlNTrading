"""
Crude-tuned strategy parameter profiles (multi-asset Phase 2).

Reused strategies (ORB / breakout / momentum) take a parameter profile so the SAME logic can run
on NIFTY or crude by swapping the profile. get_profile(None) returns the NIFTY baseline, which
documents today's hard-coded NIFTY behavior — passing None must never change NIFTY output (the
regression-safety mechanism for Phase 2 Step G).

⚠️ CRUDE values are PROVISIONAL first cuts based on crude's materially higher intraday range
(~2-4% vs NIFTY's typical <1%), expressed as multipliers over the NIFTY baseline — NOT arbitrary
constants and NOT final. They must be confirmed by the historical-volatility comparison documented
in the phase report before any live-small enablement.
"""
from typing import Optional

# NIFTY baseline — a faithful record of the current hard-coded NIFTY strategy parameters. Passing
# no profile (None) resolves to this, so NIFTY behavior is unchanged.
NIFTY_PROFILE = {
    "asset_class": "INDEX_OPTIONS",
    "sl_multiplier": 1.0,          # baseline (1.0 == current NIFTY SL distance)
    "target_multiplier": 1.0,
    "breakout_buffer_mult": 1.0,   # candle-range breakout buffer scaling
    "min_confidence": 85,          # matches the CHOPPY high-confidence override threshold
}

# Crude profile — PROVISIONAL. Wider SL/target and breakout buffer for crude's larger intraday range.
CRUDE_PROFILE = {
    "asset_class": "CRUDE_OIL_OPTIONS",
    "sl_multiplier": 1.75,         # PROVISIONAL — confirm vs historical vol study
    "target_multiplier": 1.75,     # PROVISIONAL
    "breakout_buffer_mult": 1.5,   # PROVISIONAL — wider buffer to avoid whipsaw on crude noise
    "min_confidence": 85,
}

_PROFILES = {
    "INDEX_OPTIONS": NIFTY_PROFILE,
    "CRUDE_OIL_OPTIONS": CRUDE_PROFILE,
}


def get_profile(asset_class: Optional[str] = None) -> dict:
    """Return the strategy parameter profile for an asset class. None/unknown -> NIFTY baseline
    (byte-identical to today's NIFTY behavior)."""
    if not asset_class:
        return NIFTY_PROFILE
    return _PROFILES.get(asset_class, NIFTY_PROFILE)
