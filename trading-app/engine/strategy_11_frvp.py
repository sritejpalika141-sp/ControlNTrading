"""
Strategy 11: Fixed Range Volume Profile (FRVP) Imbalance & Acceleration Engine.

Trades Low Volume Nodes (LVN liquidity vacuums) and High Volume Node (HVN / POC) mean-reversion rejections:
- LVN Breakout: Price entering thin volume zone accelerates toward next HVN target.
- POC Rejection: Price piercing POC / HVN zone with candlestick rejection reverses toward opposite Value Area boundary.
"""
import asyncio
from typing import Dict, List, Optional
from engine.volume_profile import compute_volume_profile


async def evaluate_frvp_strategy(
    client, state, symbol: str, candles_5m: List[Dict], candles_daily: List[Dict] = None, vix: float = 15.0
) -> Optional[Dict]:
    """
    Evaluates Strategy 11 (FRVP) on 5m candles for a target symbol.
    Returns signal dict if valid setup found, else None.
    """
    if not candles_5m or len(candles_5m) < 30:
        return None

    # Compute volume profile over recent 40 5-min bars (~3.3 hours fixed range)
    window = candles_5m[-40:]
    vp = compute_volume_profile(window, num_bins=35)
    poc = vp["poc"]
    vah = vp["vah"]
    val = vp["val"]

    if poc <= 0:
        return None

    last_candle = candles_5m[-1]
    prev_candle = candles_5m[-2]
    spot = last_candle["close"]

    is_green = last_candle["close"] > last_candle["open"]
    is_red = last_candle["close"] < last_candle["open"]

    # Distance from POC in percentage
    poc_dist_pct = abs(spot - poc) / poc * 100.0

    # 1. LVN Liquidity Vacuum Acceleration Trade
    # Look for current candle inside an LVN bin moving with strong momentum
    current_lvn = False
    for lvn in vp["lvns"]:
        if abs(spot - lvn["price"]) / spot * 100.0 <= 0.3:
            current_lvn = True
            break

    if current_lvn:
        if is_green and spot > prev_candle["high"]:
            # Bullish LVN Vacuum Acceleration -> Target VAH or next HVN above
            target = max(vah, spot + abs(spot - val) * 0.8)
            sl = min([c["low"] for c in window[-3:]]) - 2.0
            risk = spot - sl
            if risk > 2.0:
                return {
                    "signal": "BUY",
                    "type": "CALL",
                    "direction": "BULLISH",
                    "strategy": "Strategy 11: FRVP LVN Vacuum",
                    "entry_price": round(spot, 2),
                    "stop_loss": round(sl, 2),
                    "sl": round(sl, 2),
                    "target": round(spot + (risk * 1.5), 2),
                    "confidence": 85,
                    "reason": f"Price entered LVN liquidity vacuum at {spot:.1f}, accelerating toward VAH ({vah:.1f})"
                }

        elif is_red and spot < prev_candle["low"]:
            # Bearish LVN Vacuum Acceleration -> Target VAL or next HVN below
            target = min(val, spot - abs(vah - spot) * 0.8)
            sl = max([c["high"] for c in window[-3:]]) + 2.0
            risk = sl - spot
            if risk > 2.0:
                return {
                    "signal": "BUY",
                    "type": "PUT",
                    "direction": "BEARISH",
                    "strategy": "Strategy 11: FRVP LVN Vacuum",
                    "entry_price": round(spot, 2),
                    "stop_loss": round(sl, 2),
                    "sl": round(sl, 2),
                    "target": round(spot - (risk * 1.5), 2),
                    "confidence": 85,
                    "reason": f"Price entered LVN liquidity vacuum at {spot:.1f}, accelerating downward toward VAL ({val:.1f})"
                }

    # 2. POC Rejection / Value Area Re-entry Trade
    # Price dips below VAL and closes back inside -> Bullish Mean Reversion to POC
    if prev_candle["low"] < val and last_candle["close"] > val and is_green:
        sl = prev_candle["low"] - 2.0
        risk = spot - sl
        if risk > 2.0:
            return {
                "signal": "BUY",
                "type": "CALL",
                "direction": "BULLISH",
                "strategy": "Strategy 11: FRVP POC Reversion",
                "entry_price": round(spot, 2),
                "stop_loss": round(sl, 2),
                "sl": round(sl, 2),
                "target": round(poc, 2),
                "confidence": 80,
                "reason": f"VAL reclaim at {spot:.1f}, mean-reverting toward POC ({poc:.1f})"
            }

    # Price rallies above VAH and closes back inside -> Bearish Mean Reversion to POC
    if prev_candle["high"] > vah and last_candle["close"] < vah and is_red:
        sl = prev_candle["high"] + 2.0
        risk = sl - spot
        if risk > 2.0:
            return {
                "signal": "BUY",
                "type": "PUT",
                "direction": "BEARISH",
                "strategy": "Strategy 11: FRVP POC Reversion",
                "entry_price": round(spot, 2),
                "stop_loss": round(sl, 2),
                "sl": round(sl, 2),
                "target": round(poc, 2),
                "confidence": 80,
                "reason": f"VAH rejection at {spot:.1f}, mean-reverting downward toward POC ({poc:.1f})"
            }

    return None
