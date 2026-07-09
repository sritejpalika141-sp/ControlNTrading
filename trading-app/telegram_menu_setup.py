import requests
import json
import re

try:
    with open('logs/trading_state_1.json') as f:
        state_data = json.load(f)
        webhook_url = state_data.get('webhook_url')
        
        if webhook_url and "api.telegram.org" in webhook_url:
            match = re.search(r"bot([^/]+)/", webhook_url)
            if match:
                bot_token = match.group(1)
                
                commands = [
                    {"command": "status", "description": "View system health and active info"},
                    {"command": "positions", "description": "List all open active trades"},
                    {"command": "strategies", "description": "Status of all active strategies"},
                    {"command": "pnl", "description": "Today's performance breakdown"},
                    {"command": "start", "description": "Resume automated trading"},
                    {"command": "stop", "description": "Emergency halt all trading"},
                    {"command": "settings", "description": "View current risk parameters"}
                ]
                
                set_url = f"https://api.telegram.org/bot{bot_token}/setMyCommands"
                response = requests.post(set_url, json={"commands": commands})
                print("Menu Setup Response:", response.json())
            else:
                print("Could not extract bot token from URL")
        else:
            print("Invalid or missing webhook URL in state")
except Exception as e:
    print(f"Error: {e}")
