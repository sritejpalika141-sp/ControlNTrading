import os
import csv
import math
import asyncio
from datetime import datetime
from state import logger, get_user_state
from engine.automation import IST
from engine.strikes import get_dynamic_lot_size

# Config for Strategy 5
PROCESS_VARIANCE = 1e-6
MEASUREMENT_VARIANCE = 1e-3
STD_LOOKBACK = 20
VOL_SMA_PERIOD = 20

# We need to maintain state for the Kalman Filter across evaluations
# Or recompute it from scratch using historical CSV + live data.
# For robustness, we will fetch data and compute it iteratively.

def compute_kalman_filter(prices, process_variance=1e-6, measurement_variance=1e-3):
    """
    1D Kalman Filter to compute Fair Value Line (FVL).
    """
    if not prices:
        return []
    
    estimates = []
    # Initialize state
    post_estimate = prices[0]
    post_error = 1.0
    
    for measurement in prices:
        # Predict Step
        prior_estimate = post_estimate
        prior_error = post_error + process_variance
        
        # Update Step
        kalman_gain = prior_error / (prior_error + measurement_variance)
        post_estimate = prior_estimate + kalman_gain * (measurement - prior_estimate)
        post_error = (1 - kalman_gain) * prior_error
        
        estimates.append(post_estimate)
        
    return estimates

def compute_sd(prices, period):
    if len(prices) < period:
        return 0.0
    recent = prices[-period:]
    mean = sum(recent) / period
    variance = sum((x - mean) ** 2 for x in recent) / period
    return math.sqrt(variance)

def compute_sma(values, period):
    if len(values) < period:
        return sum(values) / len(values) if values else 0.0
    return sum(values[-period:]) / period

_3m_cache = {"ts": 0, "closes": [], "volumes": []}

async def get_live_3m_candles(client):
    """
    Fetch today's 3-minute candles for NIFTY 50 via Fyers API.
    Cached for 15 seconds to prevent rate limits.
    """
    global _3m_cache
    now = datetime.now(IST).timestamp()
    if now - _3m_cache["ts"] < 15:
        return _3m_cache["closes"], _3m_cache["volumes"]

    try:
        # Fetch 5 days back to ensure enough data for Kalman warmup (STD_LOOKBACK=20)
        res = await asyncio.to_thread(client.get_historical, "NSE:NIFTY50-INDEX", "3", days_back=5)
        if res and len(res) > 0:
            closes = [float(c["close"]) for c in res]
            volumes = [float(c["volume"]) for c in res]
            _3m_cache = {"ts": now, "closes": closes, "volumes": volumes}
            return closes, volumes
        else:
            # Prevent 429 spam by caching the failure
            _3m_cache["ts"] = now + 45
    except Exception as e:
        logger.error(f"Strategy 5: Live history error: {e}")
        _3m_cache["ts"] = now + 45
    return [], []

async def evaluate_strat5_strategy(client, state):
    """
    Strategy 5: Optimized Aerospace Mean Reversion
    """
    now = datetime.now(IST)
    current_time_str = now.strftime("%H:%M:%S")
    
    # 1. Trading Window Constraint (Midday Block removed as requested)
    if "09:15:00" > current_time_str or current_time_str > "15:15:00":
        return None
        
    # Check if active
    if "Strategy 5: Optimized Aerospace Mean Reversion" not in state.active_strategies:
        return None

    import state as global_state
    if global_state.market_regime in ["STRONG_TREND_UP", "STRONG_TREND_DOWN"]:
        # Block Mean Reversion during very strong trends to avoid catching falling knives
        return None
        
    # Check if triggered today already (if limited to 1 trade, though not explicitly stated, we limit to 1 active)
    # Actually, we shouldn't trigger if already active.
    for t in state.active_auto_trades:
        if t.get("strategy") == "Strategy 5: Optimized Aerospace Mean Reversion":
            return None
            
    # 2. Get Data (Fyers API only, cached)
    all_closes, all_vols = await get_live_3m_candles(client)
    
    if len(all_closes) < STD_LOOKBACK + 2:
        return None
        
    # 3. Compute State Estimator (Kalman FVL)
    fvl_estimates = compute_kalman_filter(all_closes, process_variance=PROCESS_VARIANCE)
    
    current_fvl = fvl_estimates[-1]
    prev_fvl = fvl_estimates[-2]
    
    # Check if FVL is flattening
    fvl_slope = abs(current_fvl - prev_fvl)
    if fvl_slope > 1.0: # Threshold for flattening
        return None
        
    # 4. Compute Boundaries
    current_sd = compute_sd(all_closes, STD_LOOKBACK)
    upper_stall = current_fvl + (2.5 * current_sd)
    lower_lift = current_fvl - (2.5 * current_sd)
    
    # 5. Volume Surge Filter (Tightened from 1.0x to 1.5x)
    current_vol = all_vols[-1]
    avg_vol = compute_sma(all_vols[:-1], VOL_SMA_PERIOD)
    if current_vol <= 1.5 * avg_vol:
        return None # Volume surge failed
        
    # 6. Trigger Logic with Candle Strength Confirmation
    current_close = all_closes[-1]
    prev_close = all_closes[-2]
    
    # Fetch live 3m candle data to calculate high/low range
    current_candle = None
    try:
        live_res = await asyncio.to_thread(client.get_historical, "NSE:NIFTY50-INDEX", "3", 0)
        if live_res and len(live_res) > 0:
            current_candle = live_res[-1]
    except:
        pass

    signal = None
    
    # Bearish Reversal (Buy PE): crossed above upper_stall previously, now closes back inside
    if prev_close > upper_stall and current_close <= upper_stall:
        if current_candle:
            c_high = float(current_candle.get("high", current_close))
            c_low = float(current_candle.get("low", current_close))
            c_range = c_high - c_low
            # Close must be in the bottom 30% of the candle
            if c_range > 0 and (current_close - c_low) / c_range <= 0.30:
                signal = "PUT"
        else:
            signal = "PUT" # Fallback if candle data unavailable
            
    # Bullish Reversal (Buy CE): crossed below lower_lift previously, now closes back inside
    elif prev_close < lower_lift and current_close >= lower_lift:
        if current_candle:
            c_high = float(current_candle.get("high", current_close))
            c_low = float(current_candle.get("low", current_close))
            c_range = c_high - c_low
            # Close must be in the top 30% of the candle
            if c_range > 0 and (c_high - current_close) / c_range <= 0.30:
                signal = "CALL"
        else:
            signal = "CALL" # Fallback
        
    if not signal:
        return None
        
    # 7. Select Contract
    spot = current_close
    expiry = await asyncio.to_thread(client.find_nearest_expiry, spot)
    if not expiry:
        return None
        
    expiry_code = expiry['code']
    atm_strike = round(spot / 50) * 50
    # For ITM/ATM, we pick ATM or slightly ITM. Let's just pick ATM.
    sym = f"NSE:NIFTY{expiry_code}{atm_strike}CE" if signal == "CALL" else f"NSE:NIFTY{expiry_code}{atm_strike}PE"
    
    # Get live LTP
    quotes = await asyncio.to_thread(client.get_quotes, [sym])
    opt_ltp = quotes.get(sym, {}).get('lp', 0)
    if not opt_ltp:
        return None
        
    logger.info(f"🚀 Strategy 5 TRIGGERED! {signal} {sym} at Nifty {spot}. FVL: {current_fvl:.2f}")
    
    return {
        "symbol": sym, # Route directly to the option symbol
        "type": signal,
        "side": "BUY",
        "strategy": "Strategy 5: Optimized Aerospace Mean Reversion",
        "reason": f"S5 {signal} Reversal at {spot}",
        "confidence": 95,
        "entry_price": opt_ltp,
        "fvl_target": current_fvl, # Store FVL milestone
        "qty": getattr(get_user_state(client.user_id), "trade_lots", 1) * get_dynamic_lot_size(sym),
        "order_type": "CO", # Cover Order
        "sl_points": opt_ltp * 0.5, # Initial wide SL for CO, will be trailed
        "target": 0.0, # No fixed target
        "is_direct_option": True,
        "strike_info": {
            "symbol": sym,
            "ltp": opt_ltp
        }
    }
