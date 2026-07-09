async def evaluate_auto_dummy_strategy(client, state, symbol: str, candles_5m: list, candles_daily: list = None, vix: float = 15.0):
    if len(candles_5m) < 2: return None
    
    last_candle = candles_5m[-1]
    prev_candle = candles_5m[-2]
    
    # Dummy logic: Buy if green candle follows red candle
    if prev_candle['Close'] < prev_candle['Open'] and last_candle['Close'] > last_candle['Open']:
        return {
            "signal": "BUY",
            "entry_price": last_candle['Close'],
            "stop_loss": last_candle['Close'] - 50,
            "target": last_candle['Close'] + 100,
            "reason": "Dummy Bullish Engulfing",
            "paper_trade_only": True
        }
        
    return None
