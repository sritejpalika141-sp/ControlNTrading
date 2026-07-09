import os
import sys
import asyncio
from datetime import datetime, timedelta
import pytz


# Add the parent directory to sys.path so we can import from trading-app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../trading-app')))

from fyers_client import FyersClient
from engine.strategy_wisdom import calculate_sma, calculate_ema, calculate_rsi

IST = pytz.timezone('Asia/Kolkata')
SYMBOL = "NSE:NIFTY50-INDEX"
DAYS_BACK = 60

class DummyState:
    def __init__(self):
        self.active_strategies = [
            "Strategy 1: OB + FVG",
            "Strategy 3: 5-Minute ORB",
            "Strategy 4: Wisdom-Aligned Pullback"
        ]
        self.active_auto_trades = []
        self.max_loss_per_day = -10000

import yfinance as yf

def run_backtest():
    print("🚀 Fetching Historical Data using yfinance for NIFTY50 (^NSEI)...")
    
    # yfinance max for 5m is 60 days
    ticker = yf.Ticker("^NSEI")
    
    df_daily = ticker.history(period="1y", interval="1d")
    df_1h = ticker.history(period="730d", interval="1h")
    df_5m = ticker.history(period="59d", interval="5m")
    
    if df_daily.empty or df_1h.empty or df_5m.empty:
        print("❌ Failed to download historical data from Yahoo Finance.")
        return
        
    print(f"✅ Data loaded: {len(df_daily)} Daily, {len(df_1h)} 1H, {len(df_5m)} 5m candles.")

    # Convert dfs to lists of dicts
    candles_daily = []
    for date, row in df_daily.iterrows():
        candles_daily.append({"timestamp": int(date.timestamp()), "open": row["Open"], "high": row["High"], "low": row["Low"], "close": row["Close"]})
        
    candles_1h = []
    for date, row in df_1h.iterrows():
        candles_1h.append({"timestamp": int(date.timestamp()), "open": row["Open"], "high": row["High"], "low": row["Low"], "close": row["Close"]})
        
    candles_5m = []
    for date, row in df_5m.iterrows():
        # Yahoo finance returns tz-aware datetime usually
        ts = int(date.timestamp())
        candles_5m.append({"timestamp": ts, "open": row["Open"], "high": row["High"], "low": row["Low"], "close": row["Close"]})

    # Group 5m candles by Date (YYYY-MM-DD)
    days_data = {}
    for c in candles_5m:
        dt = datetime.fromtimestamp(c["timestamp"], IST)
        date_str = dt.strftime("%Y-%m-%d")
        if date_str not in days_data:
            days_data[date_str] = []
        days_data[date_str].append(c)
        
    results = {
        "Strategy 1: OB+FVG": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0},
        "Strategy 3: 5-Min ORB": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0},
        "Strategy 4: Wisdom Pullback": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0}
    }

    # Simulation Variables
    strat4_max_trades_per_day = 2
    
    print("\n⏳ Running Simulation...")
    
    for date_str, daily_5m in sorted(days_data.items()):
        # Precompute higher timeframe indicators up to this date
        hist_daily = [c for c in candles_daily if datetime.fromtimestamp(c["timestamp"], IST).strftime("%Y-%m-%d") < date_str]
        hist_1h = [c for c in candles_1h if datetime.fromtimestamp(c["timestamp"], IST).strftime("%Y-%m-%d") <= date_str]
        
        # State trackers for the day
        s3_triggered = False
        s4_trades_today = 0
        s1_triggered = False
        
        # Extract ORB limits for Strategy 3
        orb_high = None
        orb_low = None
        for c in daily_5m:
            dt = datetime.fromtimestamp(c["timestamp"], IST)
            if dt.hour == 9 and dt.minute == 15:
                orb_high = c["high"]
                orb_low = c["low"]
                break
                
        # Simulate Minute by Minute (using 5m candles)
        for i, c in enumerate(daily_5m):
            dt = datetime.fromtimestamp(c["timestamp"], IST)
            current_time = dt.strftime("%H:%M:%S")
            
            # ---------------------------------------------------------
            # STRATEGY 3: 5-Min ORB
            # ---------------------------------------------------------
            if not s3_triggered and orb_high and orb_low:
                if "09:20:00" <= current_time <= "09:30:00":
                    if c["close"] > orb_high:
                        # Long Triggered
                        s3_triggered = True
                        results["Strategy 3: 5-Min ORB"]["trades"] += 1
                        # Simulate result (1:2 RR, 20 SL, 40 TP)
                        # We just look ahead in the day to see which hits first
                        hit = simulate_trade(c["close"], "LONG", 20, 40, daily_5m[i:])
                        update_results(results["Strategy 3: 5-Min ORB"], hit)
                    elif c["close"] < orb_low:
                        # Short Triggered
                        s3_triggered = True
                        results["Strategy 3: 5-Min ORB"]["trades"] += 1
                        hit = simulate_trade(c["close"], "SHORT", 20, 40, daily_5m[i:])
                        update_results(results["Strategy 3: 5-Min ORB"], hit)

            # ---------------------------------------------------------
            # STRATEGY 4: Wisdom-Aligned Pullback
            # ---------------------------------------------------------
            if s4_trades_today < strat4_max_trades_per_day and "09:20:00" <= current_time <= "15:00:00":
                if len(hist_daily) >= 50 and len(hist_1h) >= 50 and i >= 20:
                    d_sma = calculate_sma([x["close"] for x in hist_daily], 50)
                    h_sma = calculate_sma([x["close"] for x in hist_1h], 50)
                    
                    if d_sma and h_sma:
                        d_bull = hist_daily[-1]["close"] > d_sma
                        h_bull = hist_1h[-1]["close"] > h_sma
                        d_bear = hist_daily[-1]["close"] < d_sma
                        h_bear = hist_1h[-1]["close"] < h_sma
                        
                        trend = "NEUTRAL"
                        if d_bull and h_bull: trend = "BULLISH"
                        elif d_bear and h_bear: trend = "BEARISH"
                        
                        if trend != "NEUTRAL":
                            m5_slice = daily_5m[:i+1]
                            closes = [x["close"] for x in m5_slice]
                            rsi = calculate_rsi(closes, 14)
                            emas = calculate_ema(closes, 20)
                            if rsi and emas:
                                ema = emas[-1]
                                touches_ema = c["low"] <= ema <= c["high"]
                                
                                if trend == "BULLISH" and rsi < 40 and touches_ema and c["close"] > c["open"]:
                                    s4_trades_today += 1
                                    results["Strategy 4: Wisdom Pullback"]["trades"] += 1
                                    hit = simulate_trade(c["close"], "LONG", 20, 40, daily_5m[i:])
                                    update_results(results["Strategy 4: Wisdom Pullback"], hit)
                                    
                                elif trend == "BEARISH" and rsi > 60 and touches_ema and c["close"] < c["open"]:
                                    s4_trades_today += 1
                                    results["Strategy 4: Wisdom Pullback"]["trades"] += 1
                                    hit = simulate_trade(c["close"], "SHORT", 20, 40, daily_5m[i:])
                                    update_results(results["Strategy 4: Wisdom Pullback"], hit)

            # ---------------------------------------------------------
            # STRATEGY 1: OB + FVG
            # ---------------------------------------------------------
            if not s1_triggered and "09:30:00" <= current_time <= "14:30:00":
                # For Strategy 1, it requires crossover of 9 EMA over 15 EMA after FVG hit.
                # Here we do a simplified check for the 9/15 crossover trend-following setup
                if i >= 15:
                    closes = [x["close"] for x in daily_5m[:i+1]]
                    ema9 = calculate_ema(closes, 9)
                    ema15 = calculate_ema(closes, 15)
                    
                    if ema9 and ema15 and len(ema9) > 1:
                        prev_9, curr_9 = ema9[-2], ema9[-1]
                        prev_15, curr_15 = ema15[-2], ema15[-1]
                        
                        bullish_cross = prev_9 <= prev_15 and curr_9 > curr_15
                        bearish_cross = prev_9 >= prev_15 and curr_9 < curr_15
                        
                        if bullish_cross:
                            s1_triggered = True
                            results["Strategy 1: OB+FVG"]["trades"] += 1
                            hit = simulate_trade(c["close"], "LONG", 20, 40, daily_5m[i:])
                            update_results(results["Strategy 1: OB+FVG"], hit)
                        elif bearish_cross:
                            s1_triggered = True
                            results["Strategy 1: OB+FVG"]["trades"] += 1
                            hit = simulate_trade(c["close"], "SHORT", 20, 40, daily_5m[i:])
                            update_results(results["Strategy 1: OB+FVG"], hit)

    print("\n" + "="*50)
    print("📈 BACKTESTING RESULTS (Last 60 Days)")
    print("="*50)
    for strat, data in results.items():
        total = data["trades"]
        wins = data["wins"]
        losses = data["losses"]
        pnl = data["pnl"]
        
        if total > 0:
            win_rate = (wins / total) * 100
            print(f"{strat}:")
            print(f"  Trades: {total} | Win Rate: {win_rate:.1f}%")
            print(f"  Wins: {wins} | Losses: {losses} | Est PnL Pts: {pnl:.1f}")
        else:
            print(f"{strat}: No trades taken.")
        print("-" * 50)


def simulate_trade(entry_price, side, sl_pts, tp_pts, future_candles):
    """Returns 'WIN' or 'LOSS' by looking at future candles."""
    if side == "LONG":
        sl_price = entry_price - sl_pts
        tp_price = entry_price + tp_pts
        for c in future_candles:
            if c["low"] <= sl_price: return "LOSS"
            if c["high"] >= tp_price: return "WIN"
    else:
        sl_price = entry_price + sl_pts
        tp_price = entry_price - tp_pts
        for c in future_candles:
            if c["high"] >= sl_price: return "LOSS"
            if c["low"] <= tp_price: return "WIN"
    # If day ends without hitting, close at last candle
    if len(future_candles) > 0:
        last_close = future_candles[-1]["close"]
        if side == "LONG":
            return "WIN" if last_close > entry_price else "LOSS"
        else:
            return "WIN" if last_close < entry_price else "LOSS"
    return "LOSS"

def update_results(strat_dict, result):
    if result == "WIN":
        strat_dict["wins"] += 1
        strat_dict["pnl"] += 40
    else:
        strat_dict["losses"] += 1
        strat_dict["pnl"] -= 20

if __name__ == "__main__":
    run_backtest()
