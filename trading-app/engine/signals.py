"""
Signal Generator — combines key levels, OB, FVG, trend to produce trade signals.
"""
from typing import List, Dict, Optional
from .key_levels import get_all_key_levels, detect_trend
from .order_blocks import detect_order_blocks, get_active_order_blocks
from .fvg import get_active_fvg, find_ob_fvg_confluence


def generate_signals(candles_1h: List[Dict], candles_5m: List[Dict],
                     spot: float, candles_daily: List[Dict] = None, vix: float = 0.0, symbol: str = "NSE:NIFTY50-INDEX", candles_1m: List[Dict] = None) -> Dict:
    """
    Master signal generator.
    Returns key levels, OBs, FVGs, confluences, trend, and trade signals.
    """
    from datetime import datetime
    import pytz
    
    # Time Filter (No new trades before 09:15 or after 15:00)
    ist = pytz.timezone('Asia/Kolkata')
    current_time = datetime.now(ist)
    is_after_open = (current_time.hour > 9) or (current_time.hour == 9 and current_time.minute >= 15)
    is_before_close = (current_time.hour < 15)
    past_entry_time = not (is_after_open and is_before_close)
    
    # Gap Analysis (Absolute Points instead of %)
    gap_points = 0.0
    gap_type = "Normal Open"
    unfilled_gap_dir = "NONE"
    
    if candles_daily and len(candles_daily) >= 2 and len(candles_5m) > 0:
        prev_close = candles_daily[-2]["close"]
        today_open = candles_daily[-1]["open"]
        if prev_close > 0:
            gap_points = today_open - prev_close
            abs_gap = abs(gap_points)
            
            # Dynamic thresholds based on scrip
            is_bnf = "BANK" in symbol.upper()
            mild_threshold = 100 if is_bnf else 40
            large_threshold = 200 if is_bnf else 80
            extreme_threshold = 400 if is_bnf else 150
            
            if abs_gap < mild_threshold: gap_type = "Normal Open"
            elif abs_gap < large_threshold: gap_type = "Mild Gap"
            elif abs_gap < extreme_threshold: gap_type = "Large Gap"
            else: gap_type = "Extreme Gap"
            
            # Check if gap is filled today
            gap_filled = False
            for c in candles_5m:
                # If Gap Up, and price went below or equal to prev_close
                if gap_points > 0 and c["low"] <= prev_close:
                    gap_filled = True
                    break
                # If Gap Down, and price went above or equal to prev_close
                if gap_points < 0 and c["high"] >= prev_close:
                    gap_filled = True
                    break
            
            if not gap_filled and gap_type != "Normal Open":
                # If gap up, gap fill is BEARISH. If gap down, gap fill is BULLISH.
                unfilled_gap_dir = "BEARISH" if gap_points > 0 else "BULLISH"
    # 1. Trend from 1H
    trend = detect_trend(candles_1h)

    # 2. Key levels from 1H
    key_levels = get_all_key_levels(candles_1h, spot, candles_daily)

    # 3. Order blocks from 5M
    all_obs = detect_order_blocks(candles_5m)
    active_obs = get_active_order_blocks(candles_5m, spot)

    # 4. FVGs from 5M
    active_fvgs = get_active_fvg(candles_5m, spot)

    # 5. Confluences
    confluences = find_ob_fvg_confluence(active_obs, active_fvgs)

    # 6. Generate trade signals
    signals = _evaluate_signals(trend, key_levels, active_obs, active_fvgs, confluences, spot, past_entry_time, vix, gap_points, candles_1m if candles_1m else candles_5m, unfilled_gap_dir)

    # 7. Break of Structure (BOS) from 5M
    from .key_levels import detect_recent_bos
    bos_events = detect_recent_bos(candles_5m)

    return {
        "spot": spot,
        "trend": trend,
        "key_levels": key_levels[:12],
        "bos_events": bos_events,
        "order_blocks": all_obs,
        "active_order_blocks": active_obs,
        "fvgs": active_fvgs,
        "confluences": confluences,
        "signals": signals,
        "gap_points": round(gap_points, 2),
        "gap_type": gap_type,
        "unfilled_gap_dir": unfilled_gap_dir
    }

def detect_retest_and_rejection(candles: List[Dict], zone: Dict, direction: str) -> Dict:
    """
    Checks if price has retested the zone and rejected out of it.
    Bullish: Dips into zone (retest), then moves up (rejection) strongly.
    Bearish: Rallies into zone (retest), then moves down (rejection) strongly.
    """
    if not candles or len(candles) < 3:
        return {"retested": False, "rejected": False}
    
    # Check last 3 candles for a retest to ensure immediate reaction
    recent = candles[-3:]
    retested = False
    rejection_move = False
    
    zone_top = zone.get("top")
    zone_bottom = zone.get("bottom")
    
    # 1. LIQUIDITY SWEEP CHECK (Instead of just a retest)
    # Price must pierce the opposite side of the zone to hunt retail stop losses.
    for c in recent:
        if direction == "BULLISH":
            # Liquidity Sweep: Candle low must drop strictly BELOW the zone's floor
            if c["low"] < zone_bottom:
                retested = True
                break
        else: # BEARISH
            # Liquidity Sweep: Candle high must pierce strictly ABOVE the zone's ceiling
            if c["high"] > zone_top:
                retested = True
                break
                
    # 2. REJECTION CHECK (Must be a strong rejection on the latest candle)
    if retested:
        last_c = candles[-1]
        prev_c = candles[-2]
        
        if direction == "BULLISH":
            # Rejection = Moving UP from zone
            # Criteria: Last candle is GREEN (close > open) AND closed above previous candle close
            if last_c["close"] > last_c["open"] and last_c["close"] > prev_c["close"] and last_c["close"] >= zone_bottom:
                rejection_move = True
        else: # BEARISH
            # Rejection = Moving DOWN from zone
            # Criteria: Last candle is RED (close < open) AND closed below previous candle close
            if last_c["close"] < last_c["open"] and last_c["close"] < prev_c["close"] and last_c["close"] <= zone_top:
                rejection_move = True
                
    return {"retested": retested, "rejected": rejection_move}

def _evaluate_signals(trend: Dict, key_levels: List[Dict], obs: List[Dict],
                      fvgs: List[Dict], confluences: List[Dict], spot: float,
                      past_entry_time: bool, vix: float, gap_points: float,
                      candles_eval: List[Dict] = [], unfilled_gap_dir: str = "NONE") -> List[Dict]:
    """Evaluate and generate actionable trade signals with Retest & Rejection logic."""
    signals = []

    # 0. Time Filter check
    if past_entry_time:
        signals.append({
            "type": "NO TRADE", "direction": "NEUTRAL",
            "reason": "Outside Trading Window (9:15 AM - 3:00 PM IST)",
            "confidence": 0, "advisory_only": True
        })
        return signals

    # Midday block removed.

    # Check if price is near a key level
    at_support = False
    at_resistance = False
    nearest_level = None

    for kl in key_levels:
        dist_pct = abs(kl["price"] - spot) / spot * 100
        if dist_pct <= 0.4:
            nearest_level = kl
            if kl["type"] in ("support", "pivot"): at_support = True
            if kl["type"] in ("resistance", "pivot"): at_resistance = True
            break

    trend_dir = trend.get("trend", "NEUTRAL")
    trend_strength = trend.get("strength", 0)

    # 1. OB & FVG signals with Retest & Rejection
    # We combine them because they follow the same logic
    all_setups = []
    for conf in confluences: all_setups.append({"dir": conf["direction"], "top": conf["zone_top"], "bottom": conf["zone_bottom"], "type": "confluence", "source": conf})
    for ob in obs: all_setups.append({"dir": ob["direction"], "top": ob["top"], "bottom": ob["bottom"], "type": "ob", "source": ob})
    for fvg in fvgs: all_setups.append({"dir": fvg["direction"], "top": fvg["top"], "bottom": fvg["bottom"], "type": "fvg", "source": fvg})

    for setup in all_setups:
        # Check Trend alignment
        if trend_dir != "NEUTRAL" and setup["dir"] != trend_dir:
            # Skip counter-trend setups unless it's a very strong OB
            if setup.get("score", 0) < 80:
                continue
            
        status = detect_retest_and_rejection(candles_eval, setup, setup["dir"])
        
        if status["retested"] and status["rejected"]:
            strategy_name = "Strategy 1: OB + FVG"
            is_bull = setup["dir"] == "BULLISH"
            
            # Entry Price Calculation
            # OB/Confluence -> Outer Edge | FVG -> Midpoint
            if setup["type"] == "fvg":
                entry_price = setup["bottom"] + (setup["top"] - setup["bottom"]) / 2
            else:
                entry_price = setup["top"] if is_bull else setup["bottom"]
            
            # SL Calculation: Dynamic based on OB/FVG edge (Opposite side of zone)
            if is_bull:
                sl_price = setup["bottom"] - 2.0
            else:
                sl_price = setup["top"] + 2.0

            # VIX Adjustment (v3.3.0)
            if vix > 18:
                sl_buffer = 4.0 # Widen SL in high volatility
                if is_bull: sl_price -= sl_buffer
                else: sl_price += sl_buffer

            confidence = min(95, 60 + (trend_strength / 5))
            if (is_bull and at_support) or (not is_bull and at_resistance):
                confidence = min(95, confidence + 15)

            # Avoid duplicate signals for same zone
            signals.append({
                "type": "CALL" if is_bull else "PUT",
                "direction": setup["dir"],
                "strategy": strategy_name,
                "reason": f"{setup['dir']} {setup['type'].upper()} Liquidity Sweep & Rejection confirmed",
                "confidence": confidence,
                "entry_price": round(entry_price, 1),
                "sl": round(sl_price, 1),
                "target": round(entry_price + (entry_price - sl_price) * 2, 1), # 1:2 RR
                "entry_zone_top": setup["top"],
                "entry_zone_bottom": setup["bottom"],
                "use_1m_option_candle": True # Flag to tell auto_trader to grab option 1M candle
            })

    # 2. Catch-all NO TRADE explanation
    if not signals:
        reason = "Waiting for OB/FVG Liquidity Sweep & Rejection..."
        if not all_setups:
            reason = "No active Order Blocks or FVGs near key levels."
            
        signals.append({
            "type": "WAITING", "direction": "NEUTRAL",
            "reason": reason,
            "confidence": 0,
            "advisory_only": True
        })

    # Deduplicate
    best_signals = {}
    for s in signals:
        dir_key = s["direction"]
        if dir_key not in best_signals or s["confidence"] > best_signals[dir_key]["confidence"]:
            best_signals[dir_key] = s

    final = sorted(list(best_signals.values()), key=lambda x: x["confidence"], reverse=True)
    return final[:3]
