"""
Strategy 4: Wisdom-Aligned Pullback
Based on principles from trading-wisdom, trading-strategist, and prediction markets.
- Daily/Hourly trend alignment (50 SMA).
- 5m Pullback entries (RSI < 40 for Longs, RSI > 60 for Shorts).
- 20 EMA touch on 5m chart.
- Strict 1:2 Risk/Reward with 2% capital risk.
- Max 2 trades per day.
"""

import asyncio
import logging
from datetime import datetime
import pytz
from typing import List, Dict, Optional

from engine.strikes import get_strike_recommendations

logger = logging.getLogger("STRATEGY_WISDOM")
IST = pytz.timezone('Asia/Kolkata')

LOT_SIZES = {
    "NSE:NIFTY50-INDEX": 65,
    "NSE:BANKNIFTY-INDEX": 30,
    "NSE:FINNIFTY-INDEX": 60,
    "NSE:MIDCPNIFTY-INDEX": 120,
    "NIFTY": 65,
    "BANKNIFTY": 30,
    "FINNIFTY": 60,
    "MIDCPNIFTY": 120
}

def calculate_sma(prices: List[float], period: int = 50) -> Optional[float]:
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period

def calculate_ema(prices: List[float], period: int = 20) -> List[float]:
    if not prices:
        return []
    
    multiplier = 2.0 / (period + 1.0)
    emas = [prices[0]]
    
    for price in prices[1:]:
        ema = (price - emas[-1]) * multiplier + emas[-1]
        emas.append(ema)
        
    return emas

def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
    if len(prices) < period + 1:
        return None
    
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    seed = deltas[:period]
    up = sum(d for d in seed if d >= 0) / period
    down = -sum(d for d in seed if d < 0) / period
    
    if down == 0:
        return 100.0
    
    rs = up / down
    rsi_val = 100.0 - (100.0 / (1.0 + rs))
    
    for delta in deltas[period:]:
        if delta > 0:
            upval = delta
            downval = 0.0
        else:
            upval = 0.0
            downval = -delta
            
        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        
        if down == 0:
            rsi_val = 100.0
        else:
            rs = up / down
            rsi_val = 100.0 - (100.0 / (1.0 + rs))
            
    return float(rsi_val)

async def evaluate_wisdom_strategy(client, state, symbol: str, candles_5m: List[Dict], candles_1h: List[Dict], candles_daily: List[Dict], vix: float = 15.0) -> Optional[Dict]:
    """
    Evaluates the Wisdom-Aligned Pullback strategy.
    """
    if "Strategy 4: Wisdom-Aligned Pullback" not in state.active_strategies:
        return None

    now = datetime.now(IST)
    current_time_str = now.strftime("%H:%M:%S")

    # Only trade between 9:20 and 15:00
    if current_time_str < "09:20:00" or current_time_str > "15:00:00":
        return None

    # Removed global active trade block as per user request to allow simultaneous trades.

    # Frequency cap: max 2 trades per day for this strategy
    # (Assuming we track strat_4_trades in state, defaulting to 0)
    strat_4_trades = getattr(state, "strat_4_trades", 0)
    if strat_4_trades >= 2:
        return None

    if len(candles_daily) < 50 or len(candles_1h) < 50 or len(candles_5m) < 20:
        logger.debug(f"Wisdom Strategy: Insufficient data for {symbol}")
        return None

    # 1. Trend Filter (50 SMA on 1H only)
    hourly_closes = [c["close"] for c in candles_1h]
    hourly_sma = calculate_sma(hourly_closes, 50)
    
    current_hourly_close = hourly_closes[-1]
    
    if not hourly_sma:
        return None
        
    hourly_bullish = current_hourly_close > hourly_sma
    hourly_bearish = current_hourly_close < hourly_sma

    trend = "NEUTRAL"
    if hourly_bullish:
        trend = "BULLISH"
    elif hourly_bearish:
        trend = "BEARISH"
        
    if trend == "NEUTRAL":
        return None # Conflicting trends, no trade

    # 2. Pullback Entry on 5m (20 EMA Bounce)
    m5_closes = [c["close"] for c in candles_5m]
    m5_opens = [c["open"] for c in candles_5m]
    m5_lows = [c["low"] for c in candles_5m]
    m5_highs = [c["high"] for c in candles_5m]
    
    current_close = m5_closes[-1]
    current_open = m5_opens[-1]
    current_low = m5_lows[-1]
    current_high = m5_highs[-1]
    
    m5_emas = calculate_ema(m5_closes, 20)
    current_ema = m5_emas[-1] if m5_emas else None
    
    if not current_ema:
        return None

    is_long_setup = False
    is_long_setup = False
    is_short_setup = False
    
    # Check if candle touches EMA
    touches_ema = current_low <= current_ema <= current_high

    # Calculate RSI
    m5_rsis = calculate_rsi(m5_closes, 14)
    current_rsi = m5_rsis if isinstance(m5_rsis, float) else None

    if not current_rsi:
        return None

    if trend == "BULLISH":
        # Pullback RSI must be < 40 and candle must close Green
        if touches_ema and current_close > current_open and current_rsi < 40.0:
            is_long_setup = True
            
    elif trend == "BEARISH":
        # Rally RSI must be > 60 and candle must close Red
        if touches_ema and current_close < current_open and current_rsi > 60.0:
            is_short_setup = True

    if not is_long_setup and not is_short_setup:
        return None

    # 3. Execution & Risk Management
    entry_price = current_close
    
    # Dynamic SL based on candle extremes, capped at 40 pts
    if is_long_setup:
        risk_points = entry_price - current_low
    else:
        risk_points = current_high - entry_price
        
    # Add small buffer and clamp
    risk_points = min(max(risk_points + 2.0, 10.0), 40.0)
    reward_points = risk_points * 2.0
    
    # Calculate Option Strike
    # We must fetch the Option Chain first to get strike recommendations
    expiry = await asyncio.to_thread(client.find_nearest_expiry, entry_price)
    if not expiry:
        logger.error(f"Strategy 4: Could not find expiry for {symbol}")
        return None

    option_chain = await asyncio.to_thread(client.get_option_chain_strikes, entry_price, expiry["code"] if expiry else None, 5, base_symbol=symbol)
    if not option_chain:
        logger.error(f"Strategy 4: Option chain empty for {symbol}")
        return None

    signal_type = "CALL" if is_long_setup else "PUT"
    
    strike_recs = get_strike_recommendations(option_chain, signal_type, entry_price, exclude_symbols=state.traded_strikes_today)
    
    if not strike_recs:
        logger.error(f"Strategy 4: No option recommendations for {symbol}")
        return None

    best_strike = strike_recs[0]
    strike_symbol = best_strike["symbol"]

    # Option Delta approx 0.55 for ATM
    option_risk = risk_points * 0.55
    option_reward = reward_points * 0.55
    
    # Fetch option live quote for exact entry price
    quote_res = await asyncio.to_thread(client.get_quotes, [strike_symbol])
    option_ltp = quote_res.get(strike_symbol, {}).get("lp", best_strike.get("ltp", 0))

    if option_ltp <= 0:
        logger.error(f"Strategy 4: Could not fetch LTP for {strike_symbol}")
        return None
    
    target_1 = option_ltp + option_reward
    
    signal = {
        "strategy_name": "Strategy 4: Wisdom-Aligned Pullback",
        "strategy": "Strategy 4: Wisdom-Aligned Pullback", # added standard key
        "symbol": symbol,
        "type": signal_type,
        "side": "BUY", # Strictly Option BUY
        "entry_price": option_ltp, 
        "sl_points": round(option_risk, 2),
        "target_points": round(option_reward, 2), # Legacy
        "target_1": round(target_1, 2), # Standardized target
        "strike_price": best_strike.get("strike", 0),
        "is_direct_option": True,
        "strike_info": {
            "symbol": strike_symbol,
            "ltp": option_ltp,
            "strike": best_strike.get("strike", 0),
            "type_label": f"Strategy 4 {signal_type}",
            "score": 90.0,
            "moneyness": best_strike.get("moneyness", "ATM")
        },
        "qty": LOT_SIZES.get(symbol, 65) * getattr(state, "trade_lots", 1),
        "risk_reward_ratio": 2.0,
        "metadata": {
            "trend": trend,
            "hourly_sma": hourly_sma,
            "m5_ema": current_ema,
            "m5_rsi": current_rsi
        }
    }
    
    return signal
