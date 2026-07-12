"""
Pre-trade liquidity / slippage guard (multi-asset Phase 2, MANDATORY safety gate for crude).

check_option_liquidity(option_quote, asset_class) -> (ok: bool, reason: str)

Enforces minimum open interest, minimum volume, and maximum bid-ask spread from the asset class's
registry risk_config. The gate applies ONLY when the asset class sets
`risk_config["liquidity_guard_required"] = True` (crude). For NIFTY (INDEX_OPTIONS), which does not
set that flag, this function returns (True, "guard not required for INDEX_OPTIONS") and is a no-op —
so wiring it in never blocks existing NIFTY order flow.

The caller MUST treat ok=False as a hard reject BEFORE place_order, log the reason
(min_oi_fail / min_volume_fail / spread_too_wide), and surface it (not silent).
"""
import logging
from engine.asset_classes import get_asset_class

logger = logging.getLogger("LIQUIDITY_GUARD")


def check_option_liquidity(option_quote: dict, asset_class: str = None):
    """option_quote: {oi, volume, bid, ask} for the option being considered.
    Returns (ok, reason). ok=True means safe to proceed to order placement."""
    ac = get_asset_class(asset_class)
    rc = ac.risk_config or {}
    if not rc.get("liquidity_guard_required"):
        return True, f"guard not required for {ac.name}"

    q = option_quote or {}
    oi = q.get("oi", 0) or 0
    volume = q.get("volume", 0) or 0
    bid = q.get("bid", 0) or 0
    ask = q.get("ask", 0) or 0

    min_oi = rc.get("min_oi", 0)
    min_volume = rc.get("min_volume", 0)
    max_spread_pct = rc.get("max_spread_pct", 100.0)

    if oi < min_oi:
        return False, f"min_oi_fail (oi={oi} < {min_oi})"
    if volume < min_volume:
        return False, f"min_volume_fail (volume={volume} < {min_volume})"
    if ask > 0:
        spread_pct = (ask - bid) / ask * 100
        if spread_pct > max_spread_pct:
            return False, f"spread_too_wide (spread={spread_pct:.2f}% > {max_spread_pct}%)"
    else:
        # No ask price -> cannot assess slippage; treat as illiquid rather than guess.
        return False, "spread_too_wide (no ask price)"

    return True, "ok"
