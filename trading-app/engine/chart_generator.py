import os
import pandas as pd
import mplfinance as mpf
from datetime import datetime
import logging

logger = logging.getLogger("DASHBOARD")

CHARTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "charts")
if not os.path.exists(CHARTS_DIR):
    try:
        os.makedirs(CHARTS_DIR)
    except Exception:
        pass

def generate_trade_chart(symbol: str, strategy_name: str, candles: list, entry_price: float = None, exit_price: float = None) -> str:
    """
    Generates a candlestick chart image for a specific trade to be analyzed by a Multimodal LLM.
    `candles` should be a list of dicts from the Fyers API: [{"timestamp": int, "open": float, "high": float, "low": float, "close": float, "volume": float}, ...]
    """
    if not candles:
        return ""
        
    try:
        df = pd.DataFrame(candles)
        if "timestamp" not in df.columns:
            # Fallback if structure is different
            if "time" in df.columns:
                df["timestamp"] = df["time"]
            else:
                return ""
                
        df["date"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
        df.set_index("date", inplace=True)
        
        # Ensure correct column names for mplfinance
        df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}, inplace=True)
        
        # Clean strategy name for filename
        clean_strat = "".join(c for c in strategy_name if c.isalnum() or c in (' ', '_')).replace(' ', '_')
        clean_sym = "".join(c for c in symbol if c.isalnum())
        filename = f"{clean_strat}_{clean_sym}_{int(datetime.now().timestamp())}.png"
        filepath = os.path.join(CHARTS_DIR, filename)
        
        hlines = dict(hlines=[], colors=[], linestyle='-.')
        if entry_price:
            hlines['hlines'].append(entry_price)
            hlines['colors'].append('green')
        if exit_price:
            hlines['hlines'].append(exit_price)
            hlines['colors'].append('red')
            
        if not hlines['hlines']:
            hlines = None

        # Generate and save the plot
        mpf.plot(df, type='candle', style='charles', volume=True, 
                 title=f"{symbol} - {strategy_name}",
                 hlines=hlines,
                 savefig=filepath)
                 
        return filepath
    except Exception as e:
        logger.error(f"Chart Generation Error for {symbol}: {e}")
        return ""
