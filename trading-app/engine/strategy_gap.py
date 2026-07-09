from typing import List, Dict, Tuple
from datetime import datetime
import pytz
import logging

logger = logging.getLogger(__name__)

async def evaluate_gap_fill_strategy(spot: float, candles_5m: List[Dict], analysis: Dict, active_symbols: List[str] = None, client=None, state=None) -> Tuple[bool, Dict]:
    """
    Evaluates Strategy 6: Gap Fill Strategy (Complete Rewrite)
    """
    if not candles_5m or not analysis or not state or not client:
        return False, {}

    # Check Time Cutoffs
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    
    # Force Exit Time (handled in auto_trader normally, but good to block entries too)
    if now.hour > 13 or (now.hour == 13 and now.minute >= 30):
        return False, {}

    import state as global_state
    # CHOPPY_SIDEWAYS no longer hard-blocks here — the high-confidence override in
    # risk_orchestrator.propose_trade allows this validated 95-confidence Gap-Fill signal through
    # in choppy markets; only sub-85 signals are skipped.
        
    # Entry Cutoff Time
    if now.hour > 10 or (now.hour == 10 and now.minute > 30):
        return False, {}
        
    # Start after 9:15
    if now.hour == 9 and now.minute < 15:
        return False, {}

    # Trade Limits
    if getattr(state, 'strat_6_trades_today', 0) >= 2:
        return False, {}

    # Fetch daily candles to calculate precise Gap %
    candles_daily = analysis.get("candles_daily")
    if not candles_daily or len(candles_daily) < 2:
        return False, {}

    prev_close = candles_daily[-2]["close"]
    today_open = candles_daily[-1]["open"]
    
    if prev_close <= 0:
        return False, {}

    gap_points = today_open - prev_close
    gap_pct = (gap_points / prev_close) * 100
    
    # Step 1: Gap Classification
    if abs(gap_pct) <= 0.2:
        return False, {} # No significant gap
        
    gap_dir = "UP" if gap_pct > 0 else "DOWN"
    high_magnitude = abs(gap_pct) > 1.0
    
    state.strat_6_gap_data = {
        "direction": gap_dir,
        "gap_pct": gap_pct,
        "high_magnitude": high_magnitude
    }

    # Extract today's 5-minute candles
    today_date = now.strftime("%Y-%m-%d")
    todays_candles = []
    for c in candles_5m:
        if c.get("timestamp") and c["timestamp"].startswith(today_date):
            todays_candles.append(c)
            
    if len(todays_candles) < 2:
        return False, {} # Need at least 2 candles (closing at 9:20 and 9:25) to trigger
        
    # Step 2: The "Rolling Setup Candle" Logic
    trigger_found = False
    setup_candle = None
    
    if gap_dir == "UP":
        # Bias: BEARISH (Buy PE)
        # We track the highest candle.
        highest_high = 0
        setup_candle = None
        
        for i in range(len(todays_candles) - 1):
            c = todays_candles[i]
            next_c = todays_candles[i+1]
            
            # Is this candle the highest we've seen today?
            if c["high"] > highest_high:
                highest_high = c["high"]
                setup_candle = c
            
            # If we have a setup candle, evaluate the next candle against it
            if setup_candle:
                # Does the next candle make a NEW high?
                if next_c["high"] > setup_candle["high"]:
                    # Wait state: the next loop will make next_c the new setup_candle
                    continue
                
                # It did NOT make a new high. Did it break below the setup candle's low?
                if next_c["close"] < setup_candle["low"] or next_c["low"] < setup_candle["low"]:
                    # TRIGGER CONDITION MET!
                    trigger_found = True
                    break
                    
    else:
        # Bias: BULLISH (Buy CE)
        # We track the lowest candle.
        lowest_low = float('inf')
        setup_candle = None
        
        for i in range(len(todays_candles) - 1):
            c = todays_candles[i]
            next_c = todays_candles[i+1]
            
            # Is this candle the lowest we've seen today?
            if c["low"] < lowest_low:
                lowest_low = c["low"]
                setup_candle = c
                
            if setup_candle:
                # Does the next candle make a NEW low?
                if next_c["low"] < setup_candle["low"]:
                    continue
                    
                # It did NOT make a new low. Did it break above the setup candle's high?
                if next_c["close"] > setup_candle["high"] or next_c["high"] > setup_candle["high"]:
                    # TRIGGER CONDITION MET!
                    trigger_found = True
                    break

    if not trigger_found:
        return False, {}

    # Check if this signal has already been traded (prevent duplicates if price hovers)
    if state.strat_6_confirmed:
        return False, {}

    # Signal triggered!
    signal_type = "PUT" if gap_dir == "UP" else "CALL"
    
    # We let auto_trader fetch the option chain to do Strike Selection 
    # to avoid double-fetching. We pass all the rules to auto_trader.
    
    # Calculate initial Stop Loss (Invalidation levels)
    # Gap Up: HOD. Gap Down: LOD.
    day_high = max(c.get("high", 0) for c in todays_candles)
    day_low = min(c.get("low", float('inf')) for c in todays_candles)
    
    # Hard Premium Stop (fallback calculated in auto_trader, but we can pass a max SL pts)
    # We will use the user's max_sl_trending from state.
    
    # Target is previous day's close
    fvl_target = prev_close

    signal_payload = {
        "strategy": "Strategy 6: Gap Fill Reversal",
        "type": signal_type,
        "side": "BUY",
        "confidence": 95,
        "entry_price": spot, 
        "sl_points": state.max_sl_trending, # Auto trader will use this as premium stop
        "target_points": abs(spot - fvl_target), # Gap fill target points
        "fvl_target": fvl_target, # Passing exact underlying target for TSL context
        "metadata": {
            "gap_dir": gap_dir,
            "gap_pct": round(gap_pct, 2),
            "invalidation_level": day_high if gap_dir == "UP" else day_low,
            "setup_candle": setup_candle
        }
    }

    # Mark as confirmed to avoid re-triggering the exact same setup instantly
    state.strat_6_confirmed = True
    state.save()

    return True, signal_payload
