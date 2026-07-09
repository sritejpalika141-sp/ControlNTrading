import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import pytz

def backtest_gap_fill(symbol):
    print(f"\n--- Backtesting Strategy 6: Gap Fill Reversal for {symbol} ---")
    
    ticker = yf.Ticker(symbol)
    df_5m = ticker.history(period="59d", interval="5m")
    
    if df_5m.empty:
        print(f"No data for {symbol}")
        return
        
    if df_5m.index.tz is None:
        df_5m.index = df_5m.index.tz_localize('UTC').tz_convert('Asia/Kolkata')
    else:
        df_5m.index = df_5m.index.tz_convert('Asia/Kolkata')
        
    dates = pd.Series(df_5m.index.date).unique()
    
    total_trades = 0
    wins = 0
    losses = 0
    total_points = 0.0
    
    for i in range(1, len(dates)):
        prev_date = dates[i-1]
        curr_date = dates[i]
        
        prev_day_data = df_5m[df_5m.index.date == prev_date]
        if prev_day_data.empty: continue
        prev_close = prev_day_data.iloc[-1]['Close']
        
        curr_day_data = df_5m[df_5m.index.date == curr_date]
        if curr_day_data.empty or len(curr_day_data) < 2: continue
        
        today_open = curr_day_data.iloc[0]['Open']
        
        gap_points = today_open - prev_close
        gap_pct = (gap_points / prev_close) * 100
        
        # Determine gap type (>0.2%)
        unfilled_gap_dir = "NONE"
        if gap_pct >= 0.2:
            unfilled_gap_dir = "UP"  # Target is prev_close (Bearish Fade - Buy PE)
        elif gap_pct <= -0.2:
            unfilled_gap_dir = "DOWN"  # Target is prev_close (Bullish Fade - Buy CE)
            
        if unfilled_gap_dir == "NONE":
            continue
            
        entry_time = None
        entry_price = 0
        sl_price = 0
        target_price = prev_close
        trade_type = ""
        
        # 9:15 to 10:30 candle evaluation
        todays_candles = []
        for idx, row in curr_day_data.iterrows():
            if idx.time() > pd.to_datetime('10:30:00').time():
                break
            todays_candles.append((idx, row['Open'], row['High'], row['Low'], row['Close']))
            
        if len(todays_candles) < 2:
            continue
            
        # Implementing Rolling Setup Candle
        if unfilled_gap_dir == "UP":
            highest_high = 0
            setup_candle = None
            
            for j in range(len(todays_candles) - 1):
                idx, o, h, l, c = todays_candles[j]
                n_idx, n_o, n_h, n_l, n_c = todays_candles[j+1]
                
                if h > highest_high:
                    highest_high = h
                    setup_candle = todays_candles[j]
                
                if setup_candle:
                    s_idx, s_o, s_h, s_l, s_c = setup_candle
                    if n_h > s_h:
                        continue
                    if n_c < s_l or n_l < s_l:
                        entry_time = n_idx
                        entry_price = n_c
                        sl_price = highest_high + 2.0 # Invalidation SL slightly above HOD
                        trade_type = "PUT"
                        break
                        
        else: # Gap Down
            lowest_low = float('inf')
            setup_candle = None
            
            for j in range(len(todays_candles) - 1):
                idx, o, h, l, c = todays_candles[j]
                n_idx, n_o, n_h, n_l, n_c = todays_candles[j+1]
                
                if l < lowest_low:
                    lowest_low = l
                    setup_candle = todays_candles[j]
                
                if setup_candle:
                    s_idx, s_o, s_h, s_l, s_c = setup_candle
                    if n_l < s_l:
                        continue
                    if n_c > s_h or n_h > s_h:
                        entry_time = n_idx
                        entry_price = n_c
                        sl_price = lowest_low - 2.0 # Invalidation SL slightly below LOD
                        trade_type = "CALL"
                        break
                        
        if entry_time is not None:
            trade_active = True
            outcome = ""
            pnl = 0
            
            post_entry_data = curr_day_data[curr_day_data.index > entry_time]
            
            for t_idx, t_row in post_entry_data.iterrows():
                # Force exit at 1:30 PM
                if t_idx.time() >= pd.to_datetime('13:30:00').time():
                    trade_active = False
                    eod_close = t_row['Close']
                    if trade_type == "PUT":
                        pnl = entry_price - eod_close
                    else:
                        pnl = eod_close - entry_price
                    outcome = "WIN (TIME)" if pnl > 0 else "LOSS (TIME)"
                    break
                    
                t_high = t_row['High']
                t_low = t_row['Low']
                
                if trade_type == "PUT":
                    if t_high >= sl_price:
                        outcome = "LOSS (SL)"
                        pnl = entry_price - sl_price
                        trade_active = False
                        break
                    if t_low <= target_price:
                        outcome = "WIN (TARGET)"
                        pnl = entry_price - target_price
                        trade_active = False
                        break
                elif trade_type == "CALL":
                    if t_low <= sl_price:
                        outcome = "LOSS (SL)"
                        pnl = sl_price - entry_price
                        trade_active = False
                        break
                    if t_high >= target_price:
                        outcome = "WIN (TARGET)"
                        pnl = target_price - entry_price
                        trade_active = False
                        break
                        
            if trade_active:
                eod_close = post_entry_data.iloc[-1]['Close'] if not post_entry_data.empty else entry_price
                if trade_type == "PUT":
                    pnl = entry_price - eod_close
                else:
                    pnl = eod_close - entry_price
                outcome = "WIN (EOD)" if pnl > 0 else "LOSS (EOD)"
                
            total_trades += 1
            if "WIN" in outcome:
                wins += 1
            else:
                losses += 1
            total_points += pnl
            
            # print(f"{curr_date} | Gap: {gap_pct:.2f}% | Entry: {entry_time.strftime('%H:%M')} | Type: {trade_type} | Outcome: {outcome} ({pnl:.1f} pts)")
            
    print("\n--- Summary ---")
    print(f"Total Trades : {total_trades}")
    print(f"Wins         : {wins}")
    print(f"Losses       : {losses}")
    win_rate = (wins/total_trades*100) if total_trades > 0 else 0
    print(f"Win Rate     : {win_rate:.1f}%")
    print(f"Net PnL (Pts): {total_points:.1f}")

if __name__ == "__main__":
    backtest_gap_fill("^NSEI")  # NIFTY 50
