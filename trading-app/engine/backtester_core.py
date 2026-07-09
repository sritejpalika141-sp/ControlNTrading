import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, time
import pytz
import asyncio
import importlib.util
import os
import sys

def fetch_5m_data(symbol="^NSEI", days=60):
    """Fetches historical 5-minute data."""
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=f"{days}d", interval="5m")
    
    if df.empty:
        return df
        
    ist = pytz.timezone('Asia/Kolkata')
    if df.index.tz is None: 
        df.index = df.index.tz_localize('UTC').tz_convert(ist)
    else: 
        df.index = df.index.tz_convert(ist)
        
    return df

async def run_backtest_for_strategy(strategy_file_path: str, symbol="^NSEI"):
    """
    Dynamically loads a strategy file and runs a historical backtest.
    """
    print(f"🚀 [Backtester] Starting deep-history backtest for: {os.path.basename(strategy_file_path)}")
    
    # 1. Dynamically import the strategy module
    spec = importlib.util.spec_from_file_location("dynamic_strategy", strategy_file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["dynamic_strategy"] = module
    spec.loader.exec_module(module)
    
    # Find the evaluate function
    eval_func = None
    for attr in dir(module):
        if attr.startswith("evaluate_auto_") and attr.endswith("_strategy"):
            eval_func = getattr(module, attr)
            break
            
    if not eval_func:
        print("❌ [Backtester] Could not find a valid evaluate_auto_*_strategy function in the file.")
        return None
        
    # 2. Fetch Data
    df = fetch_5m_data(symbol, days=60)
    if df.empty:
        print("❌ [Backtester] Failed to fetch historical data.")
        return None
        
    print(f"📊 [Backtester] Loaded {len(df)} candles of historical data.")
    
    # 3. Simulate
    trades = []
    active_trade = None
    
    dates = pd.Series(df.index.date).unique()
    
    for day_i in range(1, len(dates)):
        curr_date = dates[day_i]
        day_df = df[df.index.date == curr_date]
        
        for idx, row in day_df.iterrows():
            t_time = idx.time()
            spot = row['Close']
            
            # --- EVALUATE EXITS ---
            if active_trade:
                if active_trade['type'] == 'CALL':
                    if spot >= active_trade['target']: 
                        active_trade['pnl'] = active_trade['target'] - active_trade['entry']
                        active_trade['exit_reason'] = 'TARGET'
                        trades.append(active_trade)
                        active_trade = None
                    elif spot <= active_trade['sl']: 
                        active_trade['pnl'] = active_trade['sl'] - active_trade['entry']
                        active_trade['exit_reason'] = 'SL'
                        trades.append(active_trade)
                        active_trade = None
                else: # PUT
                    if spot <= active_trade['target']: 
                        active_trade['pnl'] = active_trade['entry'] - active_trade['target']
                        active_trade['exit_reason'] = 'TARGET'
                        trades.append(active_trade)
                        active_trade = None
                    elif spot >= active_trade['sl']: 
                        active_trade['pnl'] = active_trade['entry'] - active_trade['sl']
                        active_trade['exit_reason'] = 'SL'
                        trades.append(active_trade)
                        active_trade = None
                        
                # End of day square off
                if active_trade and t_time >= time(15, 15):
                    if active_trade['type'] == 'CALL':
                        active_trade['pnl'] = spot - active_trade['entry']
                    else:
                        active_trade['pnl'] = active_trade['entry'] - spot
                    active_trade['exit_reason'] = 'EOD'
                    trades.append(active_trade)
                    active_trade = None

            # --- EVALUATE ENTRIES ---
            if not active_trade and t_time >= time(9, 15) and t_time < time(15, 0):
                # Build context for strategy (list of dicts up to this point)
                # Optimization: Only pass last 50 candles to avoid massive memory overhead
                curr_history = df[df.index <= idx].tail(50)
                if len(curr_history) < 2: continue
                
                # Convert to dict format expected by framework
                candles_5m = curr_history.reset_index().rename(columns={'Datetime': 'datetime'}).to_dict('records')
                
                # Mock state and client
                state = {"active_trades": 0, "lots": 1}
                client = None
                
                try:
                    signal_dict = await eval_func(client, state, symbol, candles_5m)
                    if signal_dict and signal_dict.get("signal") in ["BUY", "SELL"]:
                        active_trade = {
                            "type": "CALL" if signal_dict["signal"] == "BUY" else "PUT",
                            "entry": signal_dict["entry_price"],
                            "sl": signal_dict["stop_loss"],
                            "target": signal_dict["target"],
                            "reason": signal_dict.get("reason", "Auto"),
                            "time": idx,
                            "pnl": 0
                        }
                except Exception as e:
                    # Ignore strategy errors in backtest loop to keep moving
                    pass

    # 4. Generate Report
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    total_pnl = sum(t['pnl'] for t in trades)
    win_rate = (len(wins) / len(trades) * 100) if trades else 0.0
    
    report = {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": f"{win_rate:.1f}%",
        "net_points": f"{total_pnl:.1f}",
        "max_drawdown": "N/A" # Simplified for V1
    }
    
    print("\n" + "="*40)
    print("📈 BACKTEST REPORT")
    print("="*40)
    for k, v in report.items():
        print(f"{k.upper()}: {v}")
    print("="*40 + "\n")
    
    return report

if __name__ == "__main__":
    # For standalone testing
    import sys
    if len(sys.argv) > 1:
        asyncio.run(run_backtest_for_strategy(sys.argv[1]))
    else:
        print("Usage: python3 backtester_core.py <path_to_strategy_file.py>")
