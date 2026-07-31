import logging
from typing import Dict, Any, Tuple, List
from datetime import datetime
import pytz

IST = pytz.timezone('Asia/Kolkata')
logger = logging.getLogger("DASHBOARD")

async def evaluate_strategy_10(symbol: str, spot: float, candles_5m: List[Dict], analysis: Dict[str, Any], client: Any, state: Any) -> Tuple[bool, Dict[str, Any]]:
    """
    Evaluates Strategy 10: Adaptive ADX Engine
    Returns (True, signal_dict) if a trade is found.
    """
    from engine.key_levels import _adx, _rsi, _ema
    
    if "Strategy 10: Adaptive ADX Engine" not in getattr(state, "active_strategies", []):
        return False, {}
        
    now = datetime.now(IST)
    
    # Run periodically (e.g. at the close of 5m candles, similar to Strategy 9)
    if not (now.minute % 5 == 0 and now.second < 20):
        return False, {}
        
    last_call = getattr(state, "strat_10_last_call", None)
    if last_call and (now - last_call).total_seconds() < 60:
        return False, {}
        
    setattr(state, "strat_10_last_call", now)
    
    # Make sure we don't already have an active trade for Strategy 10
    for t in getattr(state, "active_auto_trades", []):
        if t.get("strategy") == "Strategy 10: Adaptive ADX Engine":
            return False, {}

    try:
        candles_15m = analysis.get("candles_15m", [])
        candles_1h = analysis.get("candles_1h", [])
        
        if len(candles_15m) < 30 or len(candles_5m) < 30 or len(candles_1h) < 2:
            return False, {}
            
        # 15m Calculations
        adx_15m = _adx(candles_15m, 14)
        closes_15m = [c["close"] for c in candles_15m]
        rsi_15m = _rsi(closes_15m, 14)
        ema_9_15m = _ema(closes_15m, 9)
        ema_21_15m = _ema(closes_15m, 21)
        
        # 1H Calculations
        closes_1h = [c["close"] for c in candles_1h]
        ema_fast_1h = _ema(closes_1h, min(8, len(closes_1h)))
        ema_slow_1h = _ema(closes_1h, min(20, len(closes_1h)))
        bias_1h = "BULLISH" if ema_fast_1h > ema_slow_1h else "BEARISH"
        
        # 5m Calculations
        closes_5m = [c["close"] for c in candles_5m]
        rsi_5m = _rsi(closes_5m, 14)
        ema_9_5m = _ema(closes_5m, 9)
        ema_21_5m = _ema(closes_5m, 21)
        
        is_trendy = adx_15m >= 25.0
        signal_direction = None
        reason = ""
        
        if is_trendy:
            # TRENDY LOGIC (EMA + MACRO)
            if ema_9_15m > ema_21_15m and ema_9_5m > ema_21_5m and bias_1h == "BULLISH":
                signal_direction = "CALL"
                reason = f"TRENDY (ADX={adx_15m:.1f}): 1H/15m/5m aligned BULLISH."
            elif ema_9_15m < ema_21_15m and ema_9_5m < ema_21_5m and bias_1h == "BEARISH":
                signal_direction = "PUT"
                reason = f"TRENDY (ADX={adx_15m:.1f}): 1H/15m/5m aligned BEARISH."
        else:
            # CHOPPY LOGIC (MEAN REVERSION via RSI)
            if rsi_15m < 35 and rsi_5m < 30:
                signal_direction = "CALL"
                reason = f"CHOPPY (ADX={adx_15m:.1f}): RSI Oversold (15m: {rsi_15m:.1f}, 5m: {rsi_5m:.1f}). Mean reversion BUY."
            elif rsi_15m > 65 and rsi_5m > 70:
                signal_direction = "PUT"
                reason = f"CHOPPY (ADX={adx_15m:.1f}): RSI Overbought (15m: {rsi_15m:.1f}, 5m: {rsi_5m:.1f}). Mean reversion SELL."

        if signal_direction:
            confidence = 80
            sl_points = 20
            target_points = 30
            
            signal_dict = {
                "type": signal_direction,
                "strategy": "Strategy 10: Adaptive ADX Engine",
                "time": now.strftime("%H:%M"),
                "confidence": confidence,
                "spot": spot,
                "reason": reason,
                "sl": spot - sl_points if signal_direction == "CALL" else spot + sl_points,
                "target_1": spot + target_points if signal_direction == "CALL" else spot - target_points,
                "target_2": spot + (target_points * 2) if signal_direction == "CALL" else spot - (target_points * 2),
                "metadata": {
                    "adx": adx_15m,
                    "rsi_15m": rsi_15m,
                    "rsi_5m": rsi_5m,
                    "regime": "TRENDY" if is_trendy else "CHOPPY"
                }
            }
            return True, signal_dict
            
    except Exception as e:
        logger.error(f"Strategy 10 error: {e}")
        
    return False, {}
