import json, os

for f in os.listdir('/Users/sritejpalika/Downloads/Sritej Trading/v5/trading-app'):
    if f.endswith('.json') and 'state' in f:
        with open(os.path.join('/Users/sritejpalika/Downloads/Sritej Trading/v5/trading-app', f), 'r') as file:
            try:
                data = json.load(file)
                print(f"File: {f}")
                
                # Check for active strategies
                if "active_strategies" in data:
                    print(f"Active Strategies: {data['active_strategies']}")
                
                # Check for active auto trades
                if "active_auto_trades" in data and data["active_auto_trades"]:
                    print("Active Auto Trades:")
                    print(json.dumps(data["active_auto_trades"], indent=2))
                else:
                    print("Active Auto Trades: None")
                    
                # Check for today's trade stats
                print(f"Trades Today: {data.get('trades_today', 0)}")
                print(f"PnL Today: {data.get('pnl_today', 0.0)}")
                print(f"Max Loss Hit: {data.get('max_loss_hit', False)}")
                
                if "traded_strikes_today" in data:
                    print(f"Traded Strikes Today: {data['traded_strikes_today']}")
                
            except Exception as e:
                print(f"Error parsing {f}: {e}")
