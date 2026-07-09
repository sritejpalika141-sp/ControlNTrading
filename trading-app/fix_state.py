import json
import os
import glob

for file in glob.glob('logs/trading_state_*.json'):
    with open(file, 'r') as f:
        data = json.load(f)
    
    modified = False
    if data.get('live_trades_today', 0) == 3:
        data['live_trades_today'] = 2
        modified = True
    if data.get('paper_trades_today', 0) == 3:
        data['paper_trades_today'] = 2
        modified = True
        
    if modified:
        with open(file, 'w') as f:
            json.dump(data, f)
        print(f"Updated {file}")
