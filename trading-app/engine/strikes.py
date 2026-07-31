"""
Strike Selection Engine — picks optimal option strikes based on spot, trend, premium budget.
"""
from typing import List, Dict, Optional
import requests
import logging
import asyncio

logger = logging.getLogger("STRIKES")

from state import get_lot_size as get_dynamic_lot_size


def select_strike(option_chain: Dict, signal_type: str, spot: float,
                  max_premium: float = 300, asset_class: str = None) -> Optional[Dict]:
    """
    Select the best strike for a given signal.

    Args:
        option_chain: Dict with 'calls', 'puts', 'atm' keys
        signal_type: 'CALL' or 'PUT'
        spot: Current spot price
        max_premium: Maximum premium budget per lot
        asset_class: multi-asset Phase 2 bridging — registry key for the strike interval.
            None -> INDEX_OPTIONS (interval 50), byte-identical to the old hard-coded fallback.

    Returns:
        Selected strike details
    """
    from engine.asset_classes import get_asset_class
    _si = get_asset_class(asset_class).strike_interval
    atm = option_chain.get("atm", round(spot / _si) * _si)

    if signal_type == "CALL":
        options = option_chain.get("calls", [])
    else:
        options = option_chain.get("puts", [])

    if not options:
        return None

    # Filter by max premium
    affordable = [o for o in options if 0 < o["ltp"] <= max_premium]
    if not affordable:
        affordable = options  # fallback to all

    # Scoring: prefer ATM for highest gamma, but consider premium budget
    best = None
    best_score = -1

    for opt in affordable:
        strike = opt["strike"]
        premium = opt["ltp"]
        dist_from_atm = abs(strike - atm)

        # Score components
        atm_score = max(0, 50 - dist_from_atm / 5)  # Closer to ATM = better
        premium_score = max(0, 30 - (premium / max_premium) * 30) if premium > 0 else 0
        volume_score = min(20, opt.get("volume", 0) / 1000000)  # Volume liquidity
        spread_score = 0
        if opt.get("bid") and opt.get("ask") and opt["ask"] > 0:
            spread_pct = (opt["ask"] - opt["bid"]) / opt["ask"] * 100
            spread_score = max(0, 10 - spread_pct * 5)

        total = atm_score + premium_score + volume_score + spread_score

        if total > best_score:
            best_score = total
            best = opt.copy()
            best["score"] = round(total, 2)
            best["distance_from_atm"] = dist_from_atm

    return best


# Strike-selection tuning (owner directive 31-07-26 — OI-change + IV + delta/theta, all segments).
DELTA_FLOOR = 0.35        # skip strikes whose |delta| is below this (too far OTM — barely moves, decays)
DELTA_IDEAL = 0.50        # reward peaks at ATM-ish delta
OI_CHANGE_WEIGHT = 0.25   # scales the OI-change positioning score (oichp is a percent)


def get_strike_recommendations(option_chain: Dict, signal_type: str, spot: float, dte: int = 5, exclude_symbols: List[str] = None, asset_class: str = None) -> List[Dict]:
    """
    Strike selection driven by OI CHANGE + IV + DELTA/THETA (owner directive 31-07-26), biased to
    ATM/near-ATM. Composite score per strike:
      • ATM proximity (stay ATM/near; expiry-day tilts one strike ITM),
      • OI-CHANGE positioning — reward strikes backed by supportive option-writer positioning
        (for a CALL: PUT-OI building below = support, CALL-OI building above = resistance to avoid;
         mirrored for a PUT),
      • DELTA — floor out far-OTM junk (|delta| < DELTA_FLOOR skipped) and reward near-ATM delta,
      • IV guard — penalise strikes whose IV is rich vs the chain median (IV-crush protection),
      • THETA guard — penalise fast time-decay, harsher on/near expiry,
      • liquidity — OI level.
    Greeks (IV/delta/theta) are computed via Black-Scholes (engine.greeks) since Fyers doesn't
    provide them. Fully defensive: if greeks can't be computed for a strike it degrades to the
    distance + OI + positioning score rather than dropping the strike. Returns the full score-ranked
    list (best first); callers that read [0] are unchanged, margin-aware callers walk down.
    """
    if signal_type in ["NO TRADE", "WAITING"]:
        return []

    from engine.asset_classes import get_asset_class
    from engine.greeks import compute_greeks
    _si = get_asset_class(asset_class).strike_interval
    atm_strike = option_chain.get("atm", round(spot / _si) * _si)
    calls = option_chain.get("calls", [])
    puts = option_chain.get("puts", [])

    if signal_type == "CALL" and not calls:
        return []
    if signal_type == "PUT" and not puts:
        return []
    if not calls and not puts:
        return []

    is_call = (signal_type == "CALL")
    t_years = max(float(dte), 0.5) / 365.0    # floor at ~half a day so near-expiry greeks stay finite

    def _oichp(o):
        try:
            return float(o.get("oi_change_pct", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    # OI-change positioning: support from PUT-OI building at/below a strike; resistance from CALL-OI
    # building at/above it (within ~2 strikes). Bullish rewards support-minus-resistance; PUT mirrors.
    band = 2 * _si

    def positioning(strike):
        support = max((_oichp(p) for p in puts if p["strike"] <= strike and (strike - p["strike"]) <= band), default=0.0)
        resistance = max((_oichp(c) for c in calls if c["strike"] >= strike and (c["strike"] - strike) <= band), default=0.0)
        support = max(-50.0, min(support, 100.0))
        resistance = max(-50.0, min(resistance, 100.0))
        return (support - resistance) if is_call else (resistance - support)

    options = calls if is_call else puts
    max_oi = max((o.get("oi", 1) for o in options), default=1) or 1
    target_price = atm_strike + ((-_si if is_call else _si) if dte <= 1 else 0)

    # Chain median IV (near-ATM) — a RELATIVE yardstick so the IV guard works across underlyings
    # whose absolute IV levels differ (index vs stock vs crude).
    near_ivs = []
    for o in options:
        if abs(o["strike"] - atm_strike) <= 3 * _si and float(o.get("ltp", 0) or 0) > 0:
            g = compute_greeks(o["ltp"], spot, o["strike"], t_years, is_call)
            if g.get("iv"):
                near_ivs.append(g["iv"])
    median_iv = sorted(near_ivs)[len(near_ivs) // 2] if near_ivs else None

    scored = []
    for opt in options:
        o = opt.copy()
        strike = o["strike"]
        if exclude_symbols and o.get("symbol", "") in exclude_symbols:
            continue
        premium = float(o.get("ltp", 0) or 0)
        g = compute_greeks(premium, spot, strike, t_years, is_call) if premium > 0 else {}
        delta = abs(g.get("delta") or 0.0)
        iv = g.get("iv") or 0.0
        theta = g.get("theta_per_day") or 0.0

        # DELTA FLOOR: with valid greeks, drop far-OTM junk that barely moves. Without greeks, keep.
        if g and delta and delta < DELTA_FLOOR:
            continue

        prox_score = max(0.0, 40.0 - abs(strike - target_price) / _si * 8.0)          # max 40
        oi_liq = (o.get("oi", 0) / max_oi) * 15.0                                       # max 15
        posn = max(-25.0, min(positioning(strike) * OI_CHANGE_WEIGHT, 25.0))           # ±25
        delta_score = max(0.0, 25.0 - abs(delta - DELTA_IDEAL) * 100.0) if g else 12.0  # max 25
        iv_pen = 0.0
        if g and median_iv and iv > median_iv * 1.15:
            iv_pen = min(15.0, (iv / median_iv - 1.15) * 60.0)                          # rich-IV penalty
        theta_pen = 0.0
        if premium > 0 and theta:
            theta_pen = min(20.0, (abs(theta) / premium) * 100.0 * (1.8 if dte <= 1 else 1.0))

        o["score"] = round(prox_score + oi_liq + posn + delta_score - iv_pen - theta_pen, 1)
        o["moneyness"] = "ITM" if (is_call and strike < spot) or (not is_call and strike > spot) else ("ATM" if strike == atm_strike else "OTM")
        o["greeks"] = {"delta": g.get("delta"), "iv": iv, "theta": theta}
        scored.append(o)

    scored.sort(key=lambda x: x["score"], reverse=True)
    for opt in scored:
        opt["type_label"] = f"{opt['moneyness']} {signal_type} (OIΔ/IV/Δ-optimized)"
    return scored

def resolve_current_commodity_expiry(prefix: str, client=None) -> str:
    """
    Resolve a high-level prefix (MCX:CRUDEOIL) into a TRADABLE Fyers future symbol.

    When a Fyers `client` is given, this defers to client.resolve_active_commodity_contract(),
    which VALIDATES the contract against the history API and rolls past an expired month — the
    fix for 'watchlist stuck on an expired 26JUL contract -> 0 candles -> no MCX trades'. Without
    a client it falls back to the naive current-calendar-month guess (may be expired mid-month).
    """
    if client is not None:
        try:
            sym = client.resolve_active_commodity_contract(prefix)
            if sym:
                return sym
        except Exception:
            pass
    from datetime import datetime
    now = datetime.now()
    year_str = str(now.year)[-2:]
    month_str = now.strftime("%b").upper()
    return f"{prefix}{year_str}{month_str}FUT"

