import yfinance as yf
import pandas as pd
from datetime import datetime, time
import pytz

# Import existing order block engine
import sys
import os
sys.path.append(os.getcwd())
from engine.order_blocks import detect_order_blocks

# --- CONFIGURATION ---
SYMBOL_SPOT = "^NSEI" # NIFTY 50
DAYS = "7d" # Limited to 7d due to yfinance 1m restriction

def fetch_historical_data():
    print("Fetching historical data...")
    ticker = yf.Ticker(SYMBOL_SPOT)
    df_1m = ticker.history(period=DAYS, interval="1m")
    df_5m = ticker.history(period="60d", interval="5m")
    
    ist = pytz.timezone('Asia/Kolkata')
    if df_1m.index.tz is None: df_1m.index = df_1m.index.tz_localize('UTC').tz_convert(ist)
    else: df_1m.index = df_1m.index.tz_convert(ist)
        
    if df_5m.index.tz is None: df_5m.index = df_5m.index.tz_localize('UTC').tz_convert(ist)
    else: df_5m.index = df_5m.index.tz_convert(ist)
        
    return df_1m, df_5m

def calculate_bollinger_bands(df, window=20, num_std=2.5):
    df['SMA'] = df['Close'].rolling(window=window).mean()
    df['STD'] = df['Close'].rolling(window=window).std()
    df['UpperBand'] = df['SMA'] + (df['STD'] * num_std)
    df['LowerBand'] = df['SMA'] - (df['STD'] * num_std)
    return df

def calculate_rsi(df, window=14):
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    df['EMA_10'] = df['Close'].ewm(span=10, adjust=False).mean()
    return df

def run_backtest():
    df_1m, df_5m = fetch_historical_data()
    df_5m = calculate_bollinger_bands(df_5m)
    df_5m = calculate_rsi(df_5m)
    
    dates = pd.Series(df_1m.index.date).unique()
    
    # Trade trackers
    trades = {
        "strat1": [], "strat2": [], "strat3": [],
        "strat4": [], "strat5": [], "strat6": []
    }
    
    for day_i in range(1, len(dates)):
        curr_date = dates[day_i]
        prev_date = dates[day_i-1]
        
        day_1m = df_1m[df_1m.index.date == curr_date]
        day_5m = df_5m[df_5m.index.date == curr_date]
        prev_5m = df_5m[df_5m.index.date == prev_date]
        
        if day_1m.empty or day_5m.empty or prev_5m.empty: continue
            
        today_open = day_1m.iloc[0]['Open']
        prev_close = prev_5m.iloc[-1]['Close']
        gap = today_open - prev_close
        
        # State variables for the day
        active_trades = []
        
        # S3 ORB variables
        orb_high = None
        orb_low = None
        s3_triggered = False
        s6_triggered = False
        s2_triggered = False
        
        for idx, row_1m in day_1m.iterrows():
            t_time = idx.time()
            spot = row_1m['Close']
            
            # --- EVALUATE EXITS ---
            for t in active_trades[:]:
                if t['type'] == 'CALL':
                    if spot >= t['target']: t['pnl'] = t['target'] - t['entry']; t['exit_reason'] = 'TARGET'; active_trades.remove(t)
                    elif spot <= t['sl']: t['pnl'] = t['sl'] - t['entry']; t['exit_reason'] = 'SL'; active_trades.remove(t)
                else:
                    if spot <= t['target']: t['pnl'] = t['entry'] - t['target']; t['exit_reason'] = 'TARGET'; active_trades.remove(t)
                    elif spot >= t['sl']: t['pnl'] = t['entry'] - t['sl']; t['exit_reason'] = 'SL'; active_trades.remove(t)
                    
                if t_time >= time(15, 15) and t in active_trades:
                    t['pnl'] = (spot - t['entry']) if t['type'] == 'CALL' else (t['entry'] - spot)
                    t['exit_reason'] = 'EOD'
                    active_trades.remove(t)

            # Build data up to this minute
            curr_5m = day_5m[day_5m.index <= idx]
            if len(curr_5m) < 2: continue
            last_5m = curr_5m.iloc[-1]
            prev_5m_c = curr_5m.iloc[-2]
            
            # --- STRATEGY 2 (9:26 180 Reversal) ---
            if t_time == time(9, 26) and not s2_triggered:
                # Based on 9:15 to 9:25 move
                m_open = day_1m.iloc[0]['Open']
                direction = "UP" if spot > m_open else "DOWN"
                
                trade = {
                    "strat": "strat2", "type": "PUT" if direction == "UP" else "CALL",
                    "entry": spot, "sl": spot + 40 if direction == "UP" else spot - 40,
                    "target": spot - 60 if direction == "UP" else spot + 60, "pnl": 0
                }
                active_trades.append(trade)
                trades['strat2'].append(trade)
                s2_triggered = True

            # --- STRATEGY 3 (ORB) ---
            if t_time == time(9, 20):
                orb_high = curr_5m.iloc[0]['High']
                orb_low = curr_5m.iloc[0]['Low']
                
            if t_time > time(9, 20) and t_time < time(14, 30) and not s3_triggered and orb_high:
                if last_5m['Close'] > orb_high:
                    trade = {"strat": "strat3", "type": "CALL", "entry": spot, "sl": orb_low, "target": spot + ((spot - orb_low) * 1.5), "pnl": 0}
                    active_trades.append(trade)
                    trades['strat3'].append(trade)
                    s3_triggered = True
                elif last_5m['Close'] < orb_low:
                    trade = {"strat": "strat3", "type": "PUT", "entry": spot, "sl": orb_high, "target": spot - ((orb_high - spot) * 1.5), "pnl": 0}
                    active_trades.append(trade)
                    trades['strat3'].append(trade)
                    s3_triggered = True

            # --- STRATEGY 5 (Aerospace BB Bounce) ---
            if not pd.isna(last_5m['LowerBand']):
                if prev_5m_c['Close'] < prev_5m_c['LowerBand'] and last_5m['Close'] > last_5m['Open']:
                    if last_5m.name.time() == t_time: # Only trigger on candle close
                        trade = {"strat": "strat5", "type": "CALL", "entry": spot, "sl": last_5m['Low'] - 10, "target": last_5m['SMA'], "pnl": 0}
                        active_trades.append(trade)
                        trades['strat5'].append(trade)
                elif prev_5m_c['Close'] > prev_5m_c['UpperBand'] and last_5m['Close'] < last_5m['Open']:
                    if last_5m.name.time() == t_time:
                        trade = {"strat": "strat5", "type": "PUT", "entry": spot, "sl": last_5m['High'] + 10, "target": last_5m['SMA'], "pnl": 0}
                        active_trades.append(trade)
                        trades['strat5'].append(trade)

            # --- STRATEGY 6 (Gap Fill) ---
            if t_time < time(10, 30) and not s6_triggered:
                if abs(gap) > 30:
                    day_h = curr_5m['High'].max()
                    day_l = curr_5m['Low'].min()
                    if gap < 0: # Gap down
                        if last_5m['Close'] > last_5m['Open'] and last_5m['Close'] > prev_5m_c['High']:
                            trade = {"strat": "strat6", "type": "CALL", "entry": spot, "sl": day_l - 10, "target": spot + (abs(gap)*0.5), "pnl": 0}
                            active_trades.append(trade)
                            trades['strat6'].append(trade)
                            s6_triggered = True
                    else: # Gap up
                        if last_5m['Close'] < last_5m['Open'] and last_5m['Close'] < prev_5m_c['Low']:
                            trade = {"strat": "strat6", "type": "PUT", "entry": spot, "sl": day_h + 10, "target": spot - (abs(gap)*0.5), "pnl": 0}
                            active_trades.append(trade)
                            trades['strat6'].append(trade)
                            s6_triggered = True

    # Print summary
    print(f"\n{'='*40}")
    print(f"BACKTEST RESULTS ({DAYS} SPOT NIFTY)")
    print(f"{'='*40}")
    
    total_pnl = 0
    
    for s_name in trades:
        strats = trades[s_name]
        wins = [t for t in strats if t['pnl'] > 0]
        losses = [t for t in strats if t['pnl'] <= 0]
        pnl = sum(t['pnl'] for t in strats)
        total_pnl += pnl
        
        print(f"\n--- {s_name.upper()} ---")
        print(f"Trades: {len(strats)} | Wins: {len(wins)} | Losses: {len(losses)}")
        if len(strats) > 0:
            print(f"Win Rate: {(len(wins)/len(strats))*100:.1f}%")
        print(f"Net Points: {pnl:.1f}")
        
    print(f"\n{'='*40}")
    print(f"GRAND TOTAL PNL: {total_pnl:.1f} points")
    print(f"{'='*40}")

if __name__ == "__main__":
    run_backtest()
