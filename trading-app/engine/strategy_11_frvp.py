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
    client, state, symbol: str, candles_5m: List[Dict], candles_1m: List[Dict] = None, candles_daily: List[Dict] = None, vix: float = 15.0
) -> Optional[Dict]:
    """
    Evaluates Strategy 11 (FRVP) on candles for a target symbol.
    - Initial SL: Lowest Low of last 3 1-minute candles (CALL) / Highest High of last 3 1-minute candles (PUT)
    - TSL: Trailed dynamically on every 1-minute candle (Lowest Low of last 3 1m candles)
    - Target: Open / Unlimited (relying on 1m TSL to catch big trends)
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

    # 1-minute 3-candle SL calculation
    sl_source = candles_1m if (candles_1m and len(candles_1m) >= 3) else candles_5m[-3:]

    # 1. LVN Liquidity Vacuum Acceleration Trade
    current_lvn = False
    for lvn in vp["lvns"]:
        if abs(spot - lvn["price"]) / spot * 100.0 <= 0.3:
            current_lvn = True
            break

    if current_lvn:
        if is_green and spot > prev_candle["high"]:
            # Bullish LVN Vacuum Acceleration -> SL = Lowest Low of last 3 1-min candles
            sl = min([float(c["low"]) for c in sl_source[-3:]]) - 0.5
            risk = spot - sl
            if risk > 1.0:
                return {
                    "signal": "BUY",
                    "type": "CALL",
                    "direction": "BULLISH",
                    "strategy": "Strategy 11: FRVP LVN Vacuum",
                    "entry_price": round(spot, 2),
                    "stop_loss": round(sl, 2),
                    "sl": round(sl, 2),
                    "target": None,  # Unlimited target to ride big trends via 1m 3-candle TSL
                    "open_target": True,
                    "tsl_mode": "1M_3_CANDLE_LOW",
                    "confidence": 88,
                    "reason": f"Price entered LVN vacuum at {spot:.1f}, SL at 1m 3-candle low ({sl:.1f}), open target for big trend"
                }

        elif is_red and spot < prev_candle["low"]:
            # Bearish LVN Vacuum Acceleration -> SL = Highest High of last 3 1-min candles
            sl = max([float(c["high"]) for c in sl_source[-3:]]) + 0.5
            risk = sl - spot
            if risk > 1.0:
                return {
                    "signal": "BUY",
                    "type": "PUT",
                    "direction": "BEARISH",
                    "strategy": "Strategy 11: FRVP LVN Vacuum",
                    "entry_price": round(spot, 2),
                    "stop_loss": round(sl, 2),
                    "sl": round(sl, 2),
                    "target": None,  # Unlimited target to ride big trends via 1m 3-candle TSL
                    "open_target": True,
                    "tsl_mode": "1M_3_CANDLE_HIGH",
                    "confidence": 88,
                    "reason": f"Price entered LVN vacuum at {spot:.1f}, SL at 1m 3-candle high ({sl:.1f}), open target for big trend"
                }

    # 2. POC Rejection / Value Area Re-entry Trade
    if prev_candle["low"] < val and last_candle["close"] > val and is_green:
        sl = min([float(c["low"]) for c in sl_source[-3:]]) - 0.5
        risk = spot - sl
        if risk > 1.0:
            return {
                "signal": "BUY",
                "type": "CALL",
                "direction": "BULLISH",
                "strategy": "Strategy 11: FRVP POC Reversion",
                "entry_price": round(spot, 2),
                "stop_loss": round(sl, 2),
                "sl": round(sl, 2),
                "target": None,  # Unlimited target to ride big trends via 1m 3-candle TSL
                "open_target": True,
                "tsl_mode": "1M_3_CANDLE_LOW",
                "confidence": 82,
                "reason": f"VAL reclaim at {spot:.1f}, SL at 1m 3-candle low ({sl:.1f}), open target for big trend"
            }

    if prev_candle["high"] > vah and last_candle["close"] < vah and is_red:
        sl = max([float(c["high"]) for c in sl_source[-3:]]) + 0.5
        risk = sl - spot
        if risk > 1.0:
            return {
                "signal": "BUY",
                "type": "PUT",
                "direction": "BEARISH",
                "strategy": "Strategy 11: FRVP POC Reversion",
                "entry_price": round(spot, 2),
                "stop_loss": round(sl, 2),
                "sl": round(sl, 2),
                "target": None,  # Unlimited target to ride big trends via 1m 3-candle TSL
                "open_target": True,
                "tsl_mode": "1M_3_CANDLE_HIGH",
                "confidence": 82,
                "reason": f"VAH rejection at {spot:.1f}, SL at 1m 3-candle high ({sl:.1f}), open target for big trend"
            }

    return None
