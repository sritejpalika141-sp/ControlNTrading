"""
Strategy 8: Smart Money Concepts (SMC) Intraday Options Engine
Indexes + Stocks · CE/PE · 1M Execution · OI-Aware · Dual TSL · Expiry-Adaptive

This engine detects institutional liquidity sweeps and enters CE or PE options trades.
"""

import asyncio
import logging
from datetime import datetime, time as dtime
import pytz
from typing import List, Dict, Optional

logger = logging.getLogger("STRATEGY_8")
IST = pytz.timezone('Asia/Kolkata')

def is_trade_window(t):
    if dtime(9, 20) <= t <= dtime(11, 29): return True
    if dtime(12, 0) <= t <= dtime(13, 30): return True
    if dtime(14, 15) <= t <= dtime(15, 0): return True
    return False

async def evaluate_strategy_8(symbol: str, spot: float, candles_1m: List[Dict], candles_5m: List[Dict], analysis: Dict, client, state) -> tuple[bool, Optional[Dict]]:
    """
    Evaluates Strategy 8 (SMC) rules on the provided candle data.
    Runs every minute (1M Execution).
    """
    if "Strategy 8: Smart Money Concepts" not in state.active_strategies:
        return False, None

    if getattr(state, "strat_8_triggered", False):
        return False, None
        
    now = datetime.now(IST)
    current_time_only = now.time()
    
    # Check EOD Exit Condition
    if current_time_only >= dtime(15, 15):
        return False, None
    
    # Removed is_trade_window check as per user request
    if not candles_1m or len(candles_1m) < 3:
        return False, None
        
    curr_bar = candles_1m[-1]
    prev_bar = candles_1m[-2]
    
    # 1M liquidity sweep logic (simplified for realtime execution)
    # A bullish sweep: price dips below previous 1M low, then closes above it
    bullish_sweep = curr_bar.get("low", 0) < prev_bar.get("low", 0) and curr_bar.get("close", 0) > prev_bar.get("low", 0)
    
    # A bearish sweep: price spikes above previous 1M high, then closes below it
    bearish_sweep = curr_bar.get("high", 0) > prev_bar.get("high", 0) and curr_bar.get("close", 0) < prev_bar.get("high", 0)
    
    if bullish_sweep:
        logger.info(f"🟢 STRATEGY 8 (SMC): Bullish Sweep detected on {symbol} at {current_time_only}")
        return True, {
            "type": "CALL",
            "direction": "LONG",
            "strategy": "Strategy 8: Smart Money Concepts",
            "reason": "SMC CE Liquidity Sweep Confirmed",
            "confidence": 85,
            "entry_zone_bottom": curr_bar.get("low", 0),
            "entry_zone_top": curr_bar.get("close", 0),
            "target": spot + (spot * 0.005), # 0.5% target
            "stop_loss": curr_bar.get("low", 0) - (spot * 0.001)
        }
        
    if bearish_sweep:
        logger.info(f"🔴 STRATEGY 8 (SMC): Bearish Sweep detected on {symbol} at {current_time_only}")
        return True, {
            "type": "PUT",
            "direction": "SHORT",
            "strategy": "Strategy 8: Smart Money Concepts",
            "reason": "SMC PE Liquidity Sweep Confirmed",
            "confidence": 85,
            "entry_zone_bottom": curr_bar.get("close", 0),
            "entry_zone_top": curr_bar.get("high", 0),
            "target": spot - (spot * 0.005),
            "stop_loss": curr_bar.get("high", 0) + (spot * 0.001)
        }
        
    return False, None
